"""Resolve explicit agent preferences against the current role catalog."""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

from .managed import digest, linked_parent
from .ui import ChoiceRow

FIELD = 'excluded_agents'
FAMILY_VERSION_FIELD = 'family_selection_version'
FAMILY_VERSION = 1
PARENTS = {'design', 'seo', 'marketing', 'product', 'security', 'tester'}


@dataclass
class Selection:
    excluded: Set[str]
    active: Set[str]
    locks: Dict[str, str]


def load_rules(root: Path):
    path = root / 'agents/selection.json'
    rules = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(rules, dict) or not isinstance(rules.get('required'), list)
            or not isinstance(rules.get('dependencies'), dict)
            or not all(isinstance(values, list) for values in rules['dependencies'].values())
            or not all(isinstance(name, str) and re.fullmatch(r'[a-z0-9-]+', name)
                       for name in rules['required'] + list(rules['dependencies'])
                       + [name for values in rules['dependencies'].values() for name in values])):
        raise ValueError('invalid role rules in ' + str(path))
    return rules['required'], rules['dependencies']


def load_families(root: Path, rules) -> Dict[str, Tuple[str, ...]]:
    path = root / 'agents/routing.json'

    def unique_object(pairs):
        result = dict(pairs)
        if len(pairs) != len(result):
            raise ValueError('duplicate routing key in ' + str(path))
        return result

    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    families = data.get('families') if isinstance(data, dict) and set(data) == {'families'} else None
    if not isinstance(families, dict) or set(families) != PARENTS:
        raise ValueError('routing must define exactly these families: ' + ', '.join(sorted(PARENTS)))
    children: Set[str] = set()
    for parent, members in families.items():
        prefix = 'test' if parent == 'tester' else parent
        if not isinstance(members, list) or not members:
            raise ValueError(f'{parent}: routing family must contain a list of children')
        for child in members:
            if (not isinstance(child, str) or not re.fullmatch(prefix + r'-[a-z0-9]+(?:-[a-z0-9]+)*', child)
                    or child in PARENTS or child in children):
                raise ValueError(f'{parent}: invalid or repeated routing child {child!r}')
            children.add(child)
    names = {source.stem for source in path.parent.glob('*.md')}
    missing = (PARENTS | children) - names
    if missing:
        raise ValueError('routing roles missing from the catalog: ' + ', '.join(sorted(missing)))
    prefixes = tuple(('test' if parent == 'tester' else parent) + '-' for parent in families)
    unmapped = {name for name in names if name.startswith(prefixes)} - children
    if unmapped:
        raise ValueError('family roles missing from routing.json: ' + ', '.join(sorted(unmapped)))
    required, dependencies = rules
    dependencies = {role for values in dependencies.values() for role in values}
    locked = children & (set(required) | dependencies)
    if locked:
        raise ValueError('family children must be optional: ' + ', '.join(sorted(locked)))
    return {parent: tuple(members) for parent, members in families.items()}


def resolve(available: Iterable[str], excluded: Iterable[str], rules) -> Selection:
    names = set(available)
    excluded = set(excluded)
    required, dependencies = rules
    required = set(required)
    if required - names:
        raise ValueError('required agents missing from role catalog: ' + ', '.join(sorted(required - names)))
    active = (names - excluded) | required
    pending = sorted(active)
    dependents: Dict[str, Set[str]] = {}
    while pending:
        role = pending.pop()
        for dependency in dependencies.get(role, ()):
            if dependency not in names:
                raise ValueError(f'{role} requires agent {dependency}, which is missing from the role catalog')
            dependents.setdefault(dependency, set()).add(role)
            if dependency not in active:
                active.add(dependency)
                pending.append(dependency)
    locks = {role: 'required by ' + ', '.join(sorted(parents)) for role, parents in dependents.items()}
    locks.update({role: 'required for the agentkit workflow' for role in required})
    return Selection(excluded, active, locks)


def saved(data: Dict) -> Set[str]:
    excluded = data.get(FIELD, [])
    if not isinstance(excluded, list) or any(not isinstance(name, str) or not re.fullmatch(r'[a-z0-9-]+', name)
                                              for name in excluded):
        raise ValueError('invalid excluded_agents in agentkit manifest')
    return set(excluded)


def restore_exclusions(data: Dict, target: str, families: Dict[str, Tuple[str, ...]]) -> Set[str]:
    excluded = saved(data)
    if FAMILY_VERSION_FIELD not in data:
        files = data.get('files', {})
        if not isinstance(files, dict):
            raise ValueError('invalid manifest files')
        for parent, children in families.items():
            if parent in excluded:
                # Legacy manifests could exclude the parent before these roles existed.
                # An existing managed child records an independent selection.
                excluded.update(child for child in children if agent_rel(child, target) not in files)
    return excluded


def explicit(available: Iterable[str], exclusions: Iterable[str], rules, *, families=None) -> Selection:
    available = set(available)
    exclusions = set(exclusions)
    unknown = exclusions - available
    if unknown:
        raise ValueError('unknown agent for --skip-agent: ' + ', '.join(sorted(unknown)))
    exclusions.update(child for parent in tuple(exclusions)
                      for child in (families or {}).get(parent, ()) if child in available)
    selected = resolve(available, exclusions, rules)
    blocked = selected.active & exclusions
    if blocked:
        reasons = ', '.join(f'{role} ({selected.locks[role]})' for role in sorted(blocked))
        raise ValueError('cannot exclude agent(s): ' + reasons)
    return selected


def agent_rel(role: str, target: str) -> str:
    return 'agents/' + role + ('.toml' if target == 'codex' else '.md')


def removal_status(path: Path, home: Path, expected_hash: str) -> str:
    if linked_parent(path, home):
        return 'linked'
    if not path.exists():
        return 'missing'
    if not expected_hash:
        return 'unmanaged'
    if not path.is_file() or digest(path) != expected_hash:
        return 'edited'
    return 'owned'


def summary(available: Iterable[str], choice: Selection, say, *, families=None) -> None:
    names = set(available)
    specialists = {child for children in (families or {}).values() for child in children}
    visible = names - specialists
    say('Selected agents: ' + ', '.join(sorted(choice.active & visible)))
    say('Excluded agents: ' + (', '.join(sorted(visible - choice.active)) or 'none'))
    for role in sorted(choice.excluded & choice.active & visible):
        say(f'  {role}: selected ({choice.locks[role]}); saved exclusion retained')


def choose(target: str, available: Tuple[str, ...], choice: Selection, rules,
           terminal, read_key, *, families=None) -> Selection:
    names = set(available)
    families = {parent: set(children) & names for parent, children in (families or {}).items()
                if parent in names}
    specialists = {child for children in families.values() for child in children}
    options = [role for role in available if role not in specialists]

    def rows():
        for role in options:
            children = families.get(role, set())
            members = children | {role}
            active = members & choice.active
            mark = 'x' if active == members else '-' if active else ' '
            details = []
            if children:
                details.append(f'{len(children)} agents')
            if mark == '-':
                details.append('partially selected')
            if role in choice.locks:
                details.append('locked: ' + choice.locks[role])
            yield ChoiceRow(role, mark, ' · '.join(details), target)

    def toggle(index):
        nonlocal choice
        role = options[index]
        children = families.get(role, set())
        if role in choice.locks and not children:
            return f'{role} is locked ({choice.locks[role]}).'
        members = children if role in choice.locks else children | {role}
        excluded = choice.excluded | members if members <= choice.active else choice.excluded - members
        choice = resolve(available, excluded, rules)
        return ''

    if not terminal.checklist('Agents — ' + target.capitalize(), read_key,
                              lambda: list(rows()), toggle):
        raise ValueError('agent selection cancelled')
    return choice
