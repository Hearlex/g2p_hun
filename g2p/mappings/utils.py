"""

Utilities used by other classes

"""
import os
import csv
from collections import defaultdict, OrderedDict
import regex as re
import json
from copy import deepcopy
from pathlib import Path
import yaml

from openpyxl import load_workbook
from typing import Dict

from g2p import exceptions
from g2p.log import LOGGER

def flatten_abbreviations(data):
    ''' Turn a CSV-sourced list of lists into a flattened DefaultDict
    '''
    default_dict = defaultdict(list)
    for line in data:
        if line[0]:
            default_dict[line[0]].extend([l for l in line[1:] if l])
    return default_dict


def expand_abbreviations(data):
    ''' Exapand a flattened DefaultDict into a CSV-formatted list of lists
    '''
    lines = []
    if data:
        for key in data.keys():
            line = [key]
            for col in data[key]:
                line.append(col)
            lines.append(line)
    if not lines:
        while len(lines) < 10:
            lines.append(['', '', '', '', '', ''])
    return lines

def unicode_escape(text):
    ''' Find any escaped characters and turn them into codepoints
    '''
    return re.sub(r"""\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{6})""", escape_to_codepoint, text)


def escape_to_codepoint(match):
    ''' Turn escape into codepoint
    '''
    hex_codepoint = match.group(1)[1:]
    return chr(int(hex_codepoint, base=16))


def create_fixed_width_lookbehind(pattern):
    '''Turn all characters into fixed width lookbehinds
    '''
    return re.sub(re.compile(r"""(?<=\(?)[\p{L}\p{M}|]+(?=\)?)""", re.U),
                  pattern_to_fixed_width_lookbehinds, pattern)


def pattern_to_fixed_width_lookbehinds(match):
    ''' Python must have fixed-width lookbehinds.
    '''
    pattern = match.group()
    pattern = sorted(pattern.split('|'), key=len, reverse=True)
    current_len = len(pattern[0])
    all_lookbehinds = []
    current_list = []
    for item in pattern:
        if len(item) == current_len:
            current_list.append(item)
        else:
            current_len = len(item)
            all_lookbehinds.append(current_list)
            current_list = [item]
        if pattern.index(item) == len(pattern) - 1:
            all_lookbehinds.append(current_list)
    all_lookbehinds = [f"(?<={'|'.join(items)})" for items in all_lookbehinds]
    return '(' + '|'.join(all_lookbehinds) + ')'

def load_from_workbook(language):
    ''' Parse mapping from Excel workbook
    '''
    work_book = load_workbook(language)
    work_sheet = work_book.active
    # Create wordlist
    mapping = []
    # Loop through rows in worksheet, create if statements for different columns
    # and append mappings to self.mapping.
    for entry in work_sheet:
        new_io = {"in": "", "out": "",
                    "context_before": "", "context_after": ""}
        for col in entry:
            if col.column == 'A':
                value = col.value
                if isinstance(value, (float, int)):
                    value = str(value)
                new_io["in"] = value
            if col.column == 'B':
                value = col.value
                if isinstance(value, (float, int)):
                    value = str(value)
                new_io["out"] = value
            if col.column == 'C':
                if col.value is not None:
                    value = col.value
                    if isinstance(value, (float, int)):
                        value = str(value)
                    new_io["context_before"] = value
            if col.column == 'D':
                if col.value is not None:
                    value = col.value
                    if isinstance(value, (float, int)):
                        value = str(value)
                    new_io["context_after"] = value
        mapping.append(new_io)

    return mapping

def load_from_csv(language):
    ''' Parse mapping from csv
    '''
    work_sheet = []
    with open(language, encoding='utf8') as f:
        reader = csv.reader(f)
        for line in reader:
            work_sheet.append(line)
    # Create wordlist
    mapping = []
    # Loop through rows in worksheet, create if statements for different columns
    # and append mappings to self.mapping.
    for entry in work_sheet:
        new_io = {"in": "", "out": "",
                    "context_before": "", "context_after": ""}
        new_io['in'] = entry[0]
        new_io['out'] = entry[1]
        try:
            new_io['context_before'] = entry[2]
        except IndexError:
            new_io['context_before'] = ''
        try:
            new_io['context_after'] = entry[3]
        except IndexError:
            new_io['context_after'] = ''
        for k in new_io:
            if isinstance(new_io[k], float) or isinstance(new_io[k], int):
                new_io[k] = str(new_io[k])
        mapping.append(new_io)

    return mapping

def load_from_file(path: str) -> list:
    ''' Helper method to load mapping from file.
    '''
    if path.endswith('csv'):
        mapping = load_from_csv(path)
    elif path.endswith('xlsx'):
        mapping = load_from_workbook(path)
    elif path.endswith('json'):
        with open(path) as f:
            mapping = json.load(f)
    return validate(mapping)


def load_mapping_from_path(path_to_mapping_config, index=0):
    ''' Loads a mapping from a path, if there is more than one mapping, then it loads based on the int
        provided to the 'index' argument. Default is 0.
    '''
    path = Path(path_to_mapping_config)
    # If path leads to actual mapping config
    if path.exists() and (path.suffix.endswith('yml') or path.suffix.endswith('yaml')):
        # safe load it
        with open(path) as f:
            mapping = yaml.safe_load(f)
        # If more than one mapping in the mapping config
        if 'mappings' in mapping:
            LOGGER.info('Loading mapping from %s between "%s" and "%s" at index %s', path_to_mapping_config, mapping['mappings'][index]['in_lang'], mapping['mappings'][index]['out_lang'], index)
            mapping = mapping['mappings'][index]
        # try to load the data from the mapping data file
        if 'mapping' in mapping:
            mapping['mapping_data'] = load_from_file(os.path.join(path.parent, mapping['mapping']))
        else:
            # Is "mapping" key missing?
            raise exceptions.MalformedMapping
        # load any abbreviations
        if 'abbreviations' in mapping:
            mapping['abbreviations_data'] = load_abbreviations_from_file(os.path.join(path.parent, mapping['abbreviations']))
        return mapping
    else:
        raise exceptions.MappingMissing

def validate(mapping):
    try:
        for io in mapping:
            if not 'context_before' in io:
                io['context_before'] = ''
            if not 'context_after' in io:
                io['context_after'] = ''
        valid = all('in' in d for d in mapping) and all('out' in d for d in mapping)
        if not valid:
            raise exceptions.MalformedMapping()     
        return mapping
    except TypeError:
        raise exceptions.MalformedMapping() # The JSON probably is not just a list (ie could be legacy readalongs format) TODO: proper exception handling

def escape_special_characters(to_escape: Dict[str, str]) -> Dict[str, str]:
    for k, v in to_escape.items():
        escaped = re.escape(v)
        if escaped != v:
            LOGGER.info(f"Escaped special characters in '{v}' with '{escaped}''. Set 'escape_special' to False in your Mapping configuration to disable this.")
        to_escape[k] = escaped
    return to_escape

def load_abbreviations_from_file(path):
    ''' Helper method to load abbreviations from file.
    '''
    if path.endswith('csv'):
        abbs = []
        with open(path, encoding='utf8') as f:
            reader = csv.reader(f)
            abbs = flatten_abbreviations(reader)
    else:
        raise exceptions.IncorrectFileType(
            '''Sorry, abbreviations must be stored as CSV files.
            You provided the following: %s''' % path)
    return abbs