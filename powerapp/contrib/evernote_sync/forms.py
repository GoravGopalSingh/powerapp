# -*- coding: utf-8 -*-
from django import forms
from evernote.edam.error.ttypes import EDAMSystemException, EDAMUserException
from powerapp.core import django_forms

from . import utils
from powerapp.core.django_widgets import SwitchWidget
from powerapp.core.exceptions import PowerAppInvalidTokenError

DEFAULT_PROJECT_NAME = u'Evernote'


class EvernoteChoiceField(forms.MultipleChoiceField):

    widget = SwitchWidget

    def populate_with_user(self, user):
        try:
            notebooks = utils.get_notebooks(user)
        except (EDAMSystemException, EDAMUserException):
            # looks like the auth token is expired, delete and re-issue it
            raise PowerAppInvalidTokenError()

        self.choices = [(n.guid, n.name) for n in notebooks]



class IntegrationForm(django_forms.IntegrationForm):
    service_label = 'evernote_sync'
    evernote_notebooks = EvernoteChoiceField(label=u'Evernote Notebook', required=False)

    def pre_save(self, integration_settings):
        """
        Perform "pre-save integration" actions
        """
        self.create_todoist_projects(integration_settings)
        self.sync_new_notebooks_pre_save(integration_settings)
        return integration_settings

    def post_save(self):
        self.sync_new_notebooks_post_save()

    def create_todoist_projects(self, integration_settings):
        """
        Create Todoist projects and map them to evernote notebooks
        """
        # a dict: project_id -> notebook guid
        projects_notebooks = integration_settings.get('projects_notebooks') or {}
        # inverted structure
        notebooks_projects = {v: k for k, v in projects_notebooks.items()}

        # a dict: notebook guid: notebook name
        notebooks = {n.guid: n.name for n in utils.get_notebooks(self.integration.user)}

        # create all projects we need to perform sync operations
        projects = []
        guids = []
        with self.integration.user.api.autocommit():
            for guid in integration_settings.get('evernote_notebooks'):
                # check that project exists
                project_id = notebooks_projects.get(guid)
                if project_id:
                    if not self.integration.user.api.projects.get_by_id(project_id):
                        project_id = None
                # if it doesn't exist, create one
                if project_id is None:
                    project_name = notebooks.get(guid, DEFAULT_PROJECT_NAME)
                    project = self.integration.user.api.projects.add(name=project_name)
                    projects.append(project)
                    guids.append(guid)

        # populate "project_notebooks" with newer values
        # at this point all projects have to have valid ids
        pids = [p['id'] for p in projects]
        projects_notebooks.update(dict(zip(pids, guids)))
        integration_settings['projects_notebooks'] = projects_notebooks
        return integration_settings

    def sync_new_notebooks_pre_save(self, integration_settings):
        """
        If integration is not new, and user adds some new notebooks to their
        watchlist, we have to perform the initial synchronization for them and
        their corresponding Todoist projects.
        """
        old_guids = self.integration.settings.get('evernote_notebooks', [])
        new_guids = integration_settings.get('evernote_notebooks', [])
        self._new_notebook_guids = set(new_guids) - set(old_guids)

    def sync_new_notebooks_post_save(self):
        if self._new_notebook_guids:
            utils.sync_evernote_projects(self.integration,
                                         self._new_notebook_guids)


