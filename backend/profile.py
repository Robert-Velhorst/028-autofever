"""Lossless saved-preview-profile boundary, separate from unsaved editor drafts."""
import copy
import re


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError('Unexpected profile fields')


def string(value, maximum, *, empty=False, identifier=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (not empty and not value.strip()):
        raise ValueError('Invalid profile text')
    if identifier and not re.fullmatch('[A-Za-z0-9_-]{1,80}', value):
        raise ValueError('Invalid profile identifier')
    return value


def identifiers(value, maximum=100):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError('Invalid profile list')
    for item in value:
        string(item, 80, identifier=True)
    if len(set(value)) != len(value):
        raise ValueError('Duplicate profile reference')
    return value


def compile_profile(profile, contacts):
    fields(profile, ('id', 'name', 'message', 'recovery', 'duration', 'checkin', 'recipients', 'overrides', 'tasks'))
    string(profile['id'], 80, identifier=True)
    for key, maximum in [('name', 80), ('message', 2000), ('recovery', 2000), ('duration', 120)]:
        string(profile[key], maximum, empty=key == 'duration')
    if type(profile['checkin']) is not int or not 1 <= profile['checkin'] <= 168:
        raise ValueError('Invalid check-in preference')
    selected = identifiers(profile['recipients'])
    if not selected or not isinstance(contacts, list) or len(contacts) != len(selected):
        raise ValueError('Supply exactly the selected saved contacts')
    people = {}
    for contact in contacts:
        fields(contact, ('id', 'name', 'group', 'phone', 'email', 'channels'))
        cid = string(contact['id'], 80, identifier=True)
        if cid in people:
            raise ValueError('Duplicate contact')
        people[cid] = contact
        for key, maximum in [('name', 80), ('group', 80), ('phone', 40), ('email', 254)]:
            string(contact[key], maximum, empty=key in ('phone', 'email'))
        # Do not silently choose a primary/fallback among multiple authorized channels.
        if (not isinstance(contact['channels'], list) or len(contact['channels']) != 1 or
                contact['channels'][0] not in ('Email', 'SMS', 'WhatsApp')):
            raise ValueError('Choose one initial Email, SMS or WhatsApp channel; fallback and Push are not connected yet')
    if set(people) != set(selected):
        raise ValueError('Contact selection mismatch')
    if not isinstance(profile['overrides'], dict):
        raise ValueError('Invalid message overrides')
    for cid, message in profile['overrides'].items():
        string(cid, 80, identifier=True)
        string(message, 2000, empty=True)
    recipients = []
    for cid in selected:
        contact = people[cid]
        channel = contact['channels'][0].lower()
        destination = contact['email'] if channel == 'email' else re.sub(r'[\s().-]', '', contact['phone'])
        recipients.append({'id': cid, 'channel': channel, 'destination': destination,
                           'message': profile['overrides'].get(cid) or profile['message']})
    if not isinstance(profile['tasks'], list) or len(profile['tasks']) > 100:
        raise ValueError('Invalid tasks')
    tasks = []
    for task in profile['tasks']:
        fields(task, ('id', 'title', 'description', 'assignees'), ('when', 'repeat', 'backup'))
        string(task['id'], 80, identifier=True)
        string(task['title'], 120)
        string(task['description'], 2000, empty=True)
        when = string(task.get('when', ''), 120, empty=True)
        helpers = identifiers(task['assignees'])
        if not helpers or not set(helpers) <= set(selected):
            raise ValueError('Invalid task assignees')
        if task.get('repeat', 'once') not in ('once', 'daily', 'weekly'):
            raise ValueError('Invalid repeat preference')
        backup = task.get('backup', '')
        string(backup, 80, empty=True)
        if backup and backup not in selected:
            raise ValueError('Invalid backup helper')
        tasks.append({'id': task['id'], 'title': task['title'], 'description': task['description'],
                      'timing': when or 'Geen tijdstip ingesteld', 'assignees': helpers})
    return {'recipients': recipients, 'tasks': tasks,
            'preparation': copy.deepcopy({'profile': profile, 'contacts': contacts})}
