#!/usr/bin/env python3
"""Convert simplified YAML back to Qt Designer .ui (XML).

Usage:
    python3 yaml2ui.py qtdragon_hd_mr1.yaml [-o qtdragon_hd_mr1_roundtrip.ui]

Reverses the ui2yaml.py conversion. Uses only stdlib — no PyYAML dependency.
Custom YAML parser handles the specific subset emitted by ui2yaml.py.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET


# ── Custom YAML parser ─────────────────────────────────────────────────
# Line-based, indentation-aware parser for the specific YAML subset
# emitted by ui2yaml.py: 2-space indent, key:value, lists, inline lists,
# quoted strings, booleans, numbers.

def parse_yaml(text):
    """Parse our YAML subset into Python dicts/lists/scalars."""
    lines = text.split('\n')
    # Strip trailing empty lines
    while lines and lines[-1].strip() == '':
        lines.pop()
    result, _ = _parse_block(lines, 0, 0)
    return result


def _indent_of(line):
    """Count leading spaces."""
    return len(line) - len(line.lstrip(' '))


def _parse_scalar(s):
    """Parse a scalar string into Python type."""
    s = s.strip()
    if not s:
        return ""
    # Quoted string
    if s.startswith('"'):
        return _parse_quoted_string(s)
    # Inline list
    if s.startswith('[') and s.endswith(']'):
        return _parse_inline_list(s)
    # Booleans
    if s == 'true':
        return True
    if s == 'false':
        return False
    # Empty dict
    if s == '{}':
        return {}
    # Empty list
    if s == '[]':
        return []
    # Integer
    try:
        return int(s)
    except ValueError:
        pass
    # Float
    try:
        return float(s)
    except ValueError:
        pass
    # Plain string
    return s


def _parse_quoted_string(s):
    """Parse a double-quoted YAML string, handling escapes."""
    # Find the closing quote, handling escaped quotes
    if not s.startswith('"'):
        return s
    i = 1
    chars = []
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            nc = s[i + 1]
            if nc == '"':
                chars.append('"')
            elif nc == '\\':
                chars.append('\\')
            elif nc == 'n':
                chars.append('\n')
            elif nc == 't':
                chars.append('\t')
            else:
                chars.append('\\')
                chars.append(nc)
            i += 2
        elif c == '"':
            break
        else:
            chars.append(c)
            i += 1
    return ''.join(chars)


def _parse_inline_list(s):
    """Parse [a, b, c] inline list."""
    inner = s[1:-1].strip()
    if not inner:
        return []
    items = []
    # Simple split on ", " — works for our subset (no nested structures)
    for item in inner.split(', '):
        items.append(_parse_scalar(item.strip()))
    return items


def _parse_block(lines, start, expected_indent):
    """Parse a block (dict or list) starting at line `start` with given indent.

    Returns (parsed_value, next_line_index).
    """
    if start >= len(lines):
        return None, start

    line = lines[start]
    stripped = line.lstrip(' ')

    # Determine if this block is a list or dict
    if stripped.startswith('- ') or stripped == '-':
        return _parse_list_block(lines, start, expected_indent)
    else:
        return _parse_dict_block(lines, start, expected_indent)


def _parse_dict_block(lines, start, expected_indent):
    """Parse a dict block."""
    result = {}
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        indent = _indent_of(line)
        if indent < expected_indent:
            break
        if indent > expected_indent:
            # Shouldn't happen at dict level, skip
            i += 1
            continue

        stripped = line.lstrip(' ')
        # Must be a key: value or key: line
        colon_pos = stripped.find(':')
        if colon_pos == -1:
            # Bare scalar — shouldn't happen in our format, skip
            i += 1
            continue

        key = stripped[:colon_pos]
        rest = stripped[colon_pos + 1:]

        if rest.strip():
            # Inline value: check for multiline quoted string
            value_str = rest.strip()
            if value_str.startswith('"') and not _is_complete_quoted(value_str):
                # Multiline quoted string — collect continuation lines
                full_str, i = _collect_multiline_quoted(lines, i, indent, value_str)
                result[key] = full_str
            else:
                result[key] = _parse_scalar(value_str)
            i += 1
        else:
            # Block value on next lines
            if i + 1 < len(lines):
                next_indent = _indent_of(lines[i + 1])
                if next_indent > expected_indent:
                    val, i = _parse_block(lines, i + 1, next_indent)
                    result[key] = val
                else:
                    # Empty value
                    result[key] = ""
                    i += 1
            else:
                result[key] = ""
                i += 1

    return result, i


def _is_complete_quoted(s):
    """Check if a quoted string is complete (has closing quote)."""
    if not s.startswith('"'):
        return True
    i = 1
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            i += 2
        elif s[i] == '"':
            return True
        else:
            i += 1
    return False


def _collect_multiline_quoted(lines, start_line, base_indent, first_part):
    """Collect a multiline quoted string that spans multiple lines."""
    parts = [first_part]
    i = start_line + 1
    while i < len(lines):
        line = lines[i]
        # Continuation line for quoted string
        parts.append(line.strip())
        combined = '\n'.join(parts)
        if _is_complete_quoted(combined):
            return _parse_quoted_string(combined), i
        i += 1
    # Didn't find closing quote — parse what we have
    return _parse_quoted_string('\n'.join(parts)), i


def _parse_list_block(lines, start, expected_indent):
    """Parse a list block."""
    result = []
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        indent = _indent_of(line)
        if indent < expected_indent:
            break
        if indent > expected_indent:
            # Continuation of previous item — shouldn't happen at list level
            i += 1
            continue

        stripped = line.lstrip(' ')
        if not stripped.startswith('- ') and stripped != '-':
            break

        if stripped == '-':
            # Bare dash — sub-block follows
            if i + 1 < len(lines):
                next_indent = _indent_of(lines[i + 1])
                val, i = _parse_block(lines, i + 1, next_indent)
                result.append(val)
            else:
                result.append(None)
                i += 1
            continue

        # "- content"
        after_dash = stripped[2:]

        # Check for "- key: value" or "- key:" (dict item)
        colon_pos = after_dash.find(':')
        if colon_pos > 0 and (colon_pos == len(after_dash) - 1 or after_dash[colon_pos + 1] == ' '):
            # Dict item in list
            item_dict = {}
            key = after_dash[:colon_pos]
            rest = after_dash[colon_pos + 1:]

            if rest.strip():
                value_str = rest.strip()
                if value_str.startswith('"') and not _is_complete_quoted(value_str):
                    full_str, i = _collect_multiline_quoted(lines, i, indent, value_str)
                    item_dict[key] = full_str
                else:
                    item_dict[key] = _parse_scalar(value_str)
                i += 1
            else:
                # Block value for first key
                if i + 1 < len(lines):
                    next_indent = _indent_of(lines[i + 1])
                    # The block content should be indented further
                    if next_indent > indent + 2:
                        val, i = _parse_block(lines, i + 1, next_indent)
                        item_dict[key] = val
                    elif next_indent == indent + 2:
                        # Could be continuation keys at same level as "- key:"
                        # The value block starts at next_indent
                        val, i = _parse_block(lines, i + 1, next_indent)
                        item_dict[key] = val
                    else:
                        item_dict[key] = ""
                        i += 1
                else:
                    item_dict[key] = ""
                    i += 1

            # Check for additional keys at indent + 2
            cont_indent = indent + 2
            while i < len(lines):
                line2 = lines[i]
                if not line2.strip():
                    i += 1
                    continue
                ind2 = _indent_of(line2)
                if ind2 != cont_indent:
                    break
                stripped2 = line2.lstrip(' ')
                cp2 = stripped2.find(':')
                if cp2 <= 0:
                    break
                key2 = stripped2[:cp2]
                rest2 = stripped2[cp2 + 1:]
                if rest2.strip():
                    vs = rest2.strip()
                    if vs.startswith('"') and not _is_complete_quoted(vs):
                        full_str, i = _collect_multiline_quoted(lines, i, ind2, vs)
                        item_dict[key2] = full_str
                    else:
                        item_dict[key2] = _parse_scalar(vs)
                    i += 1
                else:
                    if i + 1 < len(lines):
                        ni = _indent_of(lines[i + 1])
                        if ni > cont_indent:
                            val2, i = _parse_block(lines, i + 1, ni)
                            item_dict[key2] = val2
                        else:
                            item_dict[key2] = ""
                            i += 1
                    else:
                        item_dict[key2] = ""
                        i += 1

            result.append(item_dict)
        else:
            # Simple scalar list item
            result.append(_parse_scalar(after_dash))
            i += 1

    return result, i


# ── Value type inference and XML emission ──────────────────────────────

# Regex patterns for value type detection
RE_GEOMETRY = re.compile(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$')
RE_SIZE = re.compile(r'^(\d+)x(\d+)$')
RE_COLOR_HEX = re.compile(r'^#([0-9a-fA-F]{6})$')
RE_COLOR_RGBA = re.compile(r'^rgba\((\d+),(\d+),(\d+),(\d+)\)$')
RE_SIZEPOLICY = re.compile(r'^(\w+)/(\w+)$')
RE_FONT = re.compile(r'^(.+?)(?:\s+(\d+)pt)?(?:\s+(bold))?(?:\s+(italic))?(?:\s+(underline))?(?:\s+(strikeout))?$')

# Property names that indicate specific types
SIZE_PROPS = {'minimumSize', 'maximumSize', 'baseSize', 'fixedSize', 'iconSize',
              'minimumSectionSize', 'defaultSectionSize', 'gridSize'}
SIZEHINT_PROPS = {'sizeHint'}
SIZEPOLICY_PROPS = {'sizePolicy'}
FONT_PROPS = {'font'}
ICON_PROPS = {'icon'}
PIXMAP_PROPS = {'pixmap'}
# Custom widget properties that are <double> in Qt Designer even when integer-valued
DOUBLE_PROPS = {'corner_radius', 'float_alt_num', 'float_num', 'height_fraction',
                'incr_angular_number', 'incr_imperial_number', 'incr_mm_number',
                'indicator_size', 'width_fraction'}
# Properties that always use <set> even with a single flag (no |)
SET_PROPS = {'alignment', 'inputMethodHints'}


def emit_xml_property_value(name, value, indent, is_attribute=False):
    """Emit the XML for a property value, returning list of lines.

    Infers the XML type from the value format and property name.
    """
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)
    sp2 = ' ' * (indent + 2)

    prop_name = name.rstrip('*')

    # Boolean
    if isinstance(value, bool):
        return [f'{sp}<bool>{"true" if value else "false"}</bool>']

    # Integer — but check if this property should be <double>
    if isinstance(value, int) and not isinstance(value, bool):
        if prop_name in DOUBLE_PROPS:
            return [f'{sp}<double>{float(value):.15f}</double>']
        return [f'{sp}<number>{value}</number>']

    # Float
    if isinstance(value, float):
        return [f'{sp}<double>{value:.15f}</double>']

    # Dict — icon
    if isinstance(value, dict) and name.rstrip('*') in ICON_PROPS:
        return _emit_iconset(value, indent)

    # Dict — could be generic sub-structure (shouldn't normally happen)
    if isinstance(value, dict):
        return _emit_iconset(value, indent)

    # List — stringlist
    if isinstance(value, list):
        lines = [f'{sp}<stringlist>']
        for item in value:
            lines.append(f'{sp1}<string>{_xml_escape(str(item))}</string>')
        lines.append(f'{sp}</stringlist>')
        return lines

    # String values — infer type from content and property name
    s = str(value)

    # sizePolicy: "H/V"
    if prop_name in SIZEPOLICY_PROPS:
        m = RE_SIZEPOLICY.match(s)
        if m:
            return _emit_sizepolicy(m.group(1), m.group(2), indent)

    # Geometry: "WxH+X+Y"
    m = RE_GEOMETRY.match(s)
    if m:
        return _emit_rect(int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)), indent)

    # Size: "WxH" for size-related properties
    if prop_name in SIZE_PROPS or prop_name in SIZEHINT_PROPS:
        m = RE_SIZE.match(s)
        if m:
            return _emit_size(int(m.group(1)), int(m.group(2)), indent)

    # Font: compact string
    if prop_name in FONT_PROPS:
        return _emit_font(s, indent)

    # Pixmap
    if prop_name in PIXMAP_PROPS:
        return [f'{sp}<pixmap>{_xml_escape(s)}</pixmap>']

    # Color: #rrggbb
    m = RE_COLOR_HEX.match(s)
    if m:
        hex_str = m.group(1)
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        return _emit_color(r, g, b, None, indent)

    # Color: rgba(r,g,b,a)
    m = RE_COLOR_RGBA.match(s)
    if m:
        r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return _emit_color(r, g, b, a, indent)

    # Set: contains | OR is a known set property with ::
    if '|' in s or (prop_name in SET_PROPS and '::' in s):
        return [f'{sp}<set>{_xml_escape(s)}</set>']

    # Enum: contains :: but not |
    if '::' in s:
        return [f'{sp}<enum>{_xml_escape(s)}</enum>']

    # buttonGroup attribute — add notr="true"
    if is_attribute and prop_name == 'buttonGroup':
        return [f'{sp}<string notr="true">{_xml_escape(s)}</string>']

    # styleSheet — add notr="true"
    if prop_name == 'styleSheet':
        if not s:
            return [f'{sp}<string notr="true"/>']
        return [f'{sp}<string notr="true">{_xml_escape(s)}</string>']

    # Default: string
    return [f'{sp}<string>{_xml_escape(s)}</string>']


def _xml_escape(s):
    """Escape special XML characters."""
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    return s


def _emit_rect(w, h, x, y, indent):
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)
    return [
        f'{sp}<rect>',
        f'{sp1}<x>{x}</x>',
        f'{sp1}<y>{y}</y>',
        f'{sp1}<width>{w}</width>',
        f'{sp1}<height>{h}</height>',
        f'{sp}</rect>',
    ]


def _emit_size(w, h, indent):
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)
    return [
        f'{sp}<size>',
        f'{sp1}<width>{w}</width>',
        f'{sp1}<height>{h}</height>',
        f'{sp}</size>',
    ]


def _emit_sizepolicy(hsizetype, vsizetype, indent):
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)
    return [
        f'{sp}<sizepolicy hsizetype="{hsizetype}" vsizetype="{vsizetype}">',
        f'{sp1}<horstretch>0</horstretch>',
        f'{sp1}<verstretch>0</verstretch>',
        f'{sp}</sizepolicy>',
    ]


def _emit_color(r, g, b, alpha, indent):
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)
    if alpha is not None:
        lines = [f'{sp}<color alpha="{alpha}">']
    else:
        lines = [f'{sp}<color>']
    lines.append(f'{sp1}<red>{r}</red>')
    lines.append(f'{sp1}<green>{g}</green>')
    lines.append(f'{sp1}<blue>{b}</blue>')
    lines.append(f'{sp}</color>')
    return lines


def _emit_font(font_str, indent):
    """Parse compact font string and emit <font> XML.

    Format: "Family NNpt [bold] [weight=NN] [italic] [underline] [strikeout]"
    """
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)

    parts = font_str.split()
    if not parts:
        return [f'{sp}<font/>']

    lines = [f'{sp}<font>']

    # Parse: family is everything before the first recognized token
    family_parts = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p.endswith('pt') and p[:-2].isdigit():
            break
        if p in ('bold', 'italic', 'underline', 'strikeout'):
            break
        if p.startswith('weight='):
            break
        family_parts.append(p)
        i += 1

    if family_parts:
        family = ' '.join(family_parts)
        lines.append(f'{sp1}<family>{_xml_escape(family)}</family>')

    pointsize = None
    bold = False
    italic = False
    underline = False
    strikeout = False
    weight = None

    while i < len(parts):
        p = parts[i]
        if p.endswith('pt') and p[:-2].isdigit():
            pointsize = int(p[:-2])
        elif p == 'bold':
            bold = True
        elif p == 'italic':
            italic = True
        elif p == 'underline':
            underline = True
        elif p == 'strikeout':
            strikeout = True
        elif p.startswith('weight='):
            weight = int(p[7:])
        i += 1

    if pointsize is not None:
        lines.append(f'{sp1}<pointsize>{pointsize}</pointsize>')
    if bold:
        lines.append(f'{sp1}<weight>75</weight>')
        lines.append(f'{sp1}<bold>true</bold>')
    elif weight is not None:
        lines.append(f'{sp1}<weight>{weight}</weight>')
    if italic:
        lines.append(f'{sp1}<italic>true</italic>')
    if underline:
        lines.append(f'{sp1}<underline>true</underline>')
    if strikeout:
        lines.append(f'{sp1}<strikeout>true</strikeout>')

    lines.append(f'{sp}</font>')
    return lines


def _emit_iconset(icon_data, indent):
    """Emit <iconset> from dict with resource/path/state keys."""
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)

    if isinstance(icon_data, str):
        # Simple path string
        return [
            f'{sp}<iconset>',
            f'{sp1}<normaloff>{_xml_escape(icon_data)}</normaloff>',
            f'{sp}</iconset>',
        ]

    resource = icon_data.get('resource', '')
    path = icon_data.get('path', '')
    states = ['normaloff', 'normalon', 'disabledoff', 'disabledon',
              'activeoff', 'activeon', 'selectedoff', 'selectedon']

    # Collect explicit states
    found_states = {}
    for state in states:
        if state in icon_data:
            found_states[state] = icon_data[state]

    # If just resource + path, it's the simple normaloff case
    if path and not found_states:
        found_states['normaloff'] = path

    res_attr = f' resource="{_xml_escape(resource)}"' if resource else ''
    lines = [f'{sp}<iconset{res_attr}>']
    for state in states:
        if state in found_states:
            lines.append(f'{sp1}<{state}>{_xml_escape(found_states[state])}</{state}>')
    lines.append(f'{sp}</iconset>')
    return lines


# ── XML tree builder ───────────────────────────────────────────────────

def build_ui_xml(data):
    """Build the complete .ui XML string from parsed YAML data."""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')

    version = data.get('ui_version', '4.0')
    lines.append(f'<ui version="{version}">')

    # Author
    author = data.get('author')
    if author:
        lines.append(f' <author>{_xml_escape(str(author))}</author>')

    # Class
    cls = data.get('class')
    if cls:
        lines.append(f' <class>{_xml_escape(str(cls))}</class>')

    # Main widget
    widget_data = data.get('widget')
    if widget_data:
        _emit_widget(widget_data, 1, lines)

    # Custom widgets
    custom_widgets = data.get('customwidgets', [])
    if custom_widgets:
        lines.append(' <customwidgets>')
        for cw in custom_widgets:
            lines.append('  <customwidget>')
            if 'class' in cw:
                lines.append(f'   <class>{_xml_escape(str(cw["class"]))}</class>')
            if 'extends' in cw:
                lines.append(f'   <extends>{_xml_escape(str(cw["extends"]))}</extends>')
            if 'header' in cw:
                lines.append(f'   <header>{_xml_escape(str(cw["header"]))}</header>')
            if cw.get('container'):
                lines.append('   <container>1</container>')
            lines.append('  </customwidget>')
        lines.append(' </customwidgets>')

    # Resources
    resources = data.get('resources', [])
    if resources:
        lines.append(' <resources>')
        for res in resources:
            lines.append(f'  <include location="{_xml_escape(str(res))}"/>')
        lines.append(' </resources>')

    # Connections
    connections = data.get('connections', [])
    if connections:
        lines.append(' <connections>')
        for conn in connections:
            lines.append('  <connection>')
            lines.append(f'   <sender>{_xml_escape(str(conn.get("sender", "")))}</sender>')
            lines.append(f'   <signal>{_xml_escape(str(conn.get("signal", "")))}</signal>')
            lines.append(f'   <receiver>{_xml_escape(str(conn.get("receiver", "")))}</receiver>')
            lines.append(f'   <slot>{_xml_escape(str(conn.get("slot", "")))}</slot>')
            lines.append('  </connection>')
        lines.append(' </connections>')

    # Slots
    slots_data = data.get('slots')
    if slots_data:
        lines.append(' <slots>')
        for sig in slots_data.get('signals', []):
            lines.append(f'  <signal>{_xml_escape(str(sig))}</signal>')
        for slot in slots_data.get('slots', []):
            lines.append(f'  <slot>{_xml_escape(str(slot))}</slot>')
        lines.append(' </slots>')

    # Button groups
    button_groups = data.get('buttongroups', [])
    if button_groups:
        lines.append(' <buttongroups>')
        for bg in button_groups:
            lines.append(f'  <buttongroup name="{_xml_escape(str(bg))}"/>')
        lines.append(' </buttongroups>')

    lines.append('</ui>')
    return '\n'.join(lines) + '\n'


def _emit_widget(widget_data, indent, lines):
    """Emit a <widget> element."""
    sp = ' ' * indent
    sp1 = ' ' * (indent + 1)

    cls = widget_data.get('class', '')
    name = widget_data.get('name', '')
    native = widget_data.get('native')

    attrs = f' class="{_xml_escape(cls)}" name="{_xml_escape(name)}"'
    if native:
        attrs += ' native="true"'
    lines.append(f'{sp}<widget{attrs}>')

    # Properties
    _emit_properties(widget_data.get('properties', {}), indent + 1, lines)

    # Attributes
    _emit_attributes(widget_data.get('attributes', {}), indent + 1, lines)

    # Children
    for child in widget_data.get('children', []):
        if 'widget' in child:
            _emit_widget(child['widget'], indent + 1, lines)
        elif 'layout' in child:
            _emit_layout(child['layout'], indent + 1, lines)
        elif 'action' in child:
            _emit_action(child['action'], indent + 1, lines)
        elif 'addaction' in child:
            lines.append(f'{sp1}<addaction name="{_xml_escape(str(child["addaction"]))}"/>')

    # Z-order
    for z in widget_data.get('zorder', []):
        lines.append(f'{sp1}<zorder>{_xml_escape(str(z))}</zorder>')

    lines.append(f'{sp}</widget>')


def _emit_action(action_data, indent, lines):
    """Emit an <action> element."""
    sp = ' ' * indent
    name = action_data.get('name', '')
    lines.append(f'{sp}<action name="{_xml_escape(name)}">')
    _emit_properties(action_data.get('properties', {}), indent + 1, lines)
    lines.append(f'{sp}</action>')


def _emit_properties(props, indent, lines):
    """Emit <property> elements from a properties dict.

    Handles compaction reversal: fixedSize, margins, star-suffix.
    """
    sp = ' ' * indent

    # Build the expanded property list
    expanded = []

    for key, value in props.items():
        # fixedSize → minimumSize + maximumSize
        if key == 'fixedSize':
            expanded.append(('minimumSize', value, None))
            expanded.append(('maximumSize', value, None))
            continue

        # margins → four margin properties
        if key == 'margins':
            if isinstance(value, list):
                margin_names = ['leftMargin', 'topMargin', 'rightMargin', 'bottomMargin']
                for mname, mval in zip(margin_names, value):
                    expanded.append((mname, mval, None))
            else:
                for mname in ['leftMargin', 'topMargin', 'rightMargin', 'bottomMargin']:
                    expanded.append((mname, value, None))
            continue

        # Star suffix → stdset="0"
        stdset = None
        prop_name = key
        if key.endswith('*'):
            prop_name = key[:-1]
            stdset = '0'

        expanded.append((prop_name, value, stdset))

    # Emit each property
    for prop_name, value, stdset in expanded:
        stdset_attr = f' stdset="{stdset}"' if stdset else ''
        lines.append(f'{sp}<property name="{_xml_escape(prop_name)}"{stdset_attr}>')
        value_lines = emit_xml_property_value(prop_name, value, indent + 1)
        lines.extend(value_lines)
        lines.append(f'{sp}</property>')


def _emit_attributes(attrs, indent, lines):
    """Emit <attribute> elements from an attributes dict."""
    sp = ' ' * indent
    for key, value in attrs.items():
        lines.append(f'{sp}<attribute name="{_xml_escape(key)}">')
        value_lines = emit_xml_property_value(key, value, indent + 1, is_attribute=True)
        lines.extend(value_lines)
        lines.append(f'{sp}</attribute>')


def _emit_layout(layout_data, indent, lines):
    """Emit a <layout> element."""
    sp = ' ' * indent

    cls = layout_data.get('class', '')
    name = layout_data.get('name', '')
    lines.append(f'{sp}<layout class="{_xml_escape(cls)}" name="{_xml_escape(name)}">')

    # Properties
    _emit_properties(layout_data.get('properties', {}), indent + 1, lines)

    # Items
    for item in layout_data.get('items', []):
        _emit_layout_item(item, indent + 1, lines)

    lines.append(f'{sp}</layout>')


def _emit_layout_item(item_data, indent, lines):
    """Emit a layout <item> element."""
    sp = ' ' * indent

    # Build item attributes
    attrs = ''
    if 'row' in item_data:
        attrs += f' row="{item_data["row"]}"'
    if 'column' in item_data:
        attrs += f' column="{item_data["column"]}"'
    if 'rowspan' in item_data:
        attrs += f' rowspan="{item_data["rowspan"]}"'
    if 'colspan' in item_data:
        attrs += f' colspan="{item_data["colspan"]}"'
    if 'alignment' in item_data:
        attrs += f' alignment="{_xml_escape(str(item_data["alignment"]))}"'

    lines.append(f'{sp}<item{attrs}>')

    if 'widget' in item_data:
        _emit_widget(item_data['widget'], indent + 1, lines)
    elif 'layout' in item_data:
        _emit_layout(item_data['layout'], indent + 1, lines)
    elif 'spacer' in item_data:
        _emit_spacer(item_data['spacer'], indent + 1, lines)

    lines.append(f'{sp}</item>')


def _emit_spacer(spacer_data, indent, lines):
    """Emit a <spacer> element."""
    sp = ' ' * indent
    name = spacer_data.get('name', '')
    name_attr = f' name="{_xml_escape(name)}"' if name else ''
    lines.append(f'{sp}<spacer{name_attr}>')
    _emit_properties(spacer_data.get('properties', {}), indent + 1, lines)
    lines.append(f'{sp}</spacer>')


# ── Override slider macro expansion ────────────────────────────────────

# Structural defaults for each override_slider component.
# For each sub-component, these properties are always the same across all
# override slider instances and are merged in during expansion.

_OVERRIDE_SLIDER_DEFAULTS = {
    'label': {
        'minimumSize': '0x20',
        'maximumSize': '16777215x20',
        'alignment': 'Qt::AlignLeading|Qt::AlignLeft|Qt::AlignVCenter',
        'margin': 0,
        'indent': 40,
    },
    'btn50': {
        'sizePolicy': 'Fixed/Fixed',
        'text': '50',
        'fixedSize': '40x30',
    },
    'btn100': {
        'sizePolicy': 'Fixed/Fixed',
        'text': '100',
        'fixedSize': '40x30',
    },
    'slider': {
        'sizePolicy': 'Preferred/Fixed',
        'minimumSize': '100x30',
        'maximumSize': '16777215x30',
        'orientation': 'Qt::Horizontal',
        'tickInterval': 10,
    },
    'status_StatusLabel': {
        'sizePolicy': 'Fixed/Fixed',
        'alignment': 'Qt::AlignCenter',
        'fixedSize': '60x26',
        'frameShape': 'QFrame::WinPanel',
        'frameShadow': 'QFrame::Sunken',
        'lineWidth': 1,
    },
    'status_QLineEdit': {
        'sizePolicy': 'Fixed/Fixed',
        'alignment': 'Qt::AlignCenter',
        'fixedSize': '60x26',
        'mouseTracking': True,
        'maxLength': 5,
        'frame': True,
        'readOnly': True,
    },
    'led': {
        'sizePolicy': 'Fixed/Fixed',
        'diameter': 15,
        'color': '#00ff00',
        'off_color*': '#000000',
        'fixedSize': '24x24',
    },
}


def _expand_override_slider(macro):
    """Expand an override_slider macro dict into a full widget dict."""

    def _merge_props(defaults_key, user_block):
        """Build properties dict: start with defaults, overlay user keys."""
        props = dict(_OVERRIDE_SLIDER_DEFAULTS.get(defaults_key, {}))
        for k, v in user_block.items():
            if k in ('class', 'name'):
                continue
            props[k] = v
        return props

    # btn50
    btn50_block = macro.get('btn50', {})
    btn50_widget = {
        'class': btn50_block.get('class', 'QPushButton'),
        'name': btn50_block.get('name', ''),
        'properties': _merge_props('btn50', btn50_block),
    }

    # slider
    slider_block = macro.get('slider', {})
    slider_widget = {
        'class': slider_block.get('class', 'StatusSlider'),
        'name': slider_block.get('name', ''),
        'properties': _merge_props('slider', slider_block),
    }

    # btn100
    btn100_block = macro.get('btn100', {})
    btn100_widget = {
        'class': btn100_block.get('class', 'QPushButton'),
        'name': btn100_block.get('name', ''),
        'properties': _merge_props('btn100', btn100_block),
    }

    # status — defaults depend on class
    status_block = macro.get('status', {})
    status_class = status_block.get('class', 'StatusLabel')
    status_widget = {
        'class': status_class,
        'name': status_block.get('name', ''),
        'properties': _merge_props(f'status_{status_class}', status_block),
    }

    # LED
    led_block = macro.get('led', {})
    led_widget = {
        'class': led_block.get('class', 'LED'),
        'name': led_block.get('name', ''),
        'properties': _merge_props('led', led_block),
    }

    # label
    label_block = macro.get('label', {})
    label_widget = {
        'class': 'QLabel',
        'name': label_block.get('name', ''),
        'properties': _merge_props('label', label_block),
    }

    # HBoxLayout with 5 items
    hlayout = {
        'class': 'QHBoxLayout',
        'name': macro.get('hlayout', ''),
        'properties': {'spacing': 4},
        'items': [
            {'widget': btn50_widget},
            {'widget': slider_widget},
            {'widget': btn100_widget},
            {'widget': status_widget},
            {'widget': led_widget},
        ],
    }

    # VBoxLayout with label + hlayout
    vlayout = {
        'class': 'QVBoxLayout',
        'name': macro.get('vlayout', ''),
        'properties': {'spacing': 0, 'margins': 0},
        'items': [
            {'widget': label_widget},
            {'layout': hlayout},
        ],
    }

    # Outer QWidget
    return {
        'class': 'QWidget',
        'name': macro.get('widget', ''),
        'native': True,
        'children': [
            {'layout': vlayout},
        ],
    }


def _expand_macros(data):
    """Recursively expand all macros in the parsed YAML tree in-place."""
    widget = data.get('widget')
    if isinstance(widget, dict):
        _expand_macros_in_widget(widget)
    return data


def _expand_macros_in_widget(widget_data):
    """Walk a widget's children, expanding macros."""
    for child in widget_data.get('children', []):
        if 'widget' in child and isinstance(child['widget'], dict):
            _expand_macros_in_widget(child['widget'])
        elif 'layout' in child and isinstance(child['layout'], dict):
            _expand_macros_in_layout(child['layout'])


def _expand_macros_in_layout(layout_data):
    """Walk a layout's items, expanding override_slider macros."""
    items = layout_data.get('items', [])
    for i, item in enumerate(items):
        if 'override_slider' in item:
            macro = item['override_slider']
            expanded = _expand_override_slider(macro)
            # Preserve grid/alignment attributes from the layout item
            new_item = {}
            for k in ('row', 'column', 'rowspan', 'colspan', 'alignment'):
                if k in item:
                    new_item[k] = item[k]
            new_item['widget'] = expanded
            items[i] = new_item
        elif 'widget' in item and isinstance(item['widget'], dict):
            _expand_macros_in_widget(item['widget'])
        elif 'layout' in item and isinstance(item['layout'], dict):
            _expand_macros_in_layout(item['layout'])


# ── Verification ───────────────────────────────────────────────────────

def verify_roundtrip(original_ui, roundtrip_ui):
    """Compare original and roundtrip .ui files structurally.

    Reports matches and categorized differences.
    """
    try:
        orig_tree = ET.parse(original_ui)
    except ET.ParseError as e:
        print(f"  ERROR: Cannot parse original .ui: {e}", file=sys.stderr)
        return False
    try:
        rt_tree = ET.parse(roundtrip_ui)
    except ET.ParseError as e:
        print(f"  ERROR: Cannot parse roundtrip .ui: {e}", file=sys.stderr)
        return False

    orig_root = orig_tree.getroot()
    rt_root = rt_tree.getroot()

    # Count elements
    def count_tag(root, tag):
        return sum(1 for _ in root.iter(tag))

    stats = {}
    for tag in ['widget', 'layout', 'item', 'spacer', 'property', 'attribute',
                 'action', 'connection', 'customwidget', 'buttongroup']:
        orig_n = count_tag(orig_root, tag)
        rt_n = count_tag(rt_root, tag)
        stats[tag] = (orig_n, rt_n)

    print("\n── Element Count Comparison ──", file=sys.stderr)
    all_ok = True
    for tag, (orig_n, rt_n) in stats.items():
        status = 'OK' if orig_n == rt_n else 'DIFF'
        if status == 'DIFF':
            all_ok = False
        print(f"  {tag:20s}: orig={orig_n:5d}  rt={rt_n:5d}  {status}", file=sys.stderr)

    # Compare widget tree by name
    def collect_widgets(root):
        """Collect widget names and classes."""
        widgets = {}
        for w in root.iter('widget'):
            name = w.get('name', '')
            cls = w.get('class', '')
            if name:
                widgets[name] = cls
        return widgets

    orig_widgets = collect_widgets(orig_root)
    rt_widgets = collect_widgets(rt_root)

    missing = set(orig_widgets.keys()) - set(rt_widgets.keys())
    extra = set(rt_widgets.keys()) - set(orig_widgets.keys())
    common = set(orig_widgets.keys()) & set(rt_widgets.keys())

    print(f"\n── Widget Comparison ──", file=sys.stderr)
    print(f"  Original widgets: {len(orig_widgets)}", file=sys.stderr)
    print(f"  Roundtrip widgets: {len(rt_widgets)}", file=sys.stderr)
    print(f"  Common: {len(common)}", file=sys.stderr)
    if missing:
        print(f"  Missing from roundtrip ({len(missing)}):", file=sys.stderr)
        for name in sorted(list(missing)[:10]):
            print(f"    - {name} ({orig_widgets[name]})", file=sys.stderr)
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more", file=sys.stderr)
        all_ok = False
    if extra:
        print(f"  Extra in roundtrip ({len(extra)}):", file=sys.stderr)
        for name in sorted(list(extra)[:10]):
            print(f"    - {name} ({rt_widgets[name]})", file=sys.stderr)
        all_ok = False

    # Compare class mismatches in common widgets
    class_mismatches = [(n, orig_widgets[n], rt_widgets[n])
                        for n in common if orig_widgets[n] != rt_widgets[n]]
    if class_mismatches:
        print(f"\n  Class mismatches ({len(class_mismatches)}):", file=sys.stderr)
        for name, orig_cls, rt_cls in class_mismatches[:10]:
            print(f"    {name}: {orig_cls} → {rt_cls}", file=sys.stderr)
        all_ok = False

    # Expected differences
    print(f"\n── Expected Differences ──", file=sys.stderr)
    expected = []
    # Dropped defaults (properties with default values)
    orig_props = count_tag(orig_root, 'property')
    rt_props = count_tag(rt_root, 'property')
    if orig_props > rt_props:
        expected.append(f"Properties: {orig_props - rt_props} fewer (dropped defaults)")
    # Designerdata dropped
    if orig_root.find('designerdata') is not None and rt_root.find('designerdata') is None:
        expected.append("designerdata section: dropped (expected)")
    # Connection hints dropped
    orig_hints = count_tag(orig_root, 'hints')
    rt_hints = count_tag(rt_root, 'hints')
    if orig_hints > rt_hints:
        expected.append(f"Connection hints: {orig_hints} → {rt_hints} (dropped)")
    # Resources deduplicated
    orig_resources = len(list(orig_root.iter('include')))
    rt_resources = len(list(rt_root.iter('include')))
    if orig_resources != rt_resources:
        expected.append(f"Resources: {orig_resources} → {rt_resources} (deduplicated)")

    if expected:
        for e in expected:
            print(f"  {e}", file=sys.stderr)
    else:
        print("  None detected", file=sys.stderr)

    return all_ok


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert simplified YAML to Qt .ui XML")
    parser.add_argument("input", help="Path to .yaml file")
    parser.add_argument("-o", "--output", help="Output .ui file (default: stdout)")
    parser.add_argument("--verify", help="Original .ui file to compare against")
    args = parser.parse_args()

    with open(args.input, 'r') as f:
        yaml_text = f.read()

    data = parse_yaml(yaml_text)
    _expand_macros(data)
    xml_text = build_ui_xml(data)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(xml_text)
        xml_lines = xml_text.count('\n')
        print(f"Wrote {len(xml_text):,} bytes ({xml_lines:,} lines) to {args.output}",
              file=sys.stderr)
    else:
        sys.stdout.write(xml_text)

    if args.verify:
        output_path = args.output or '/tmp/_yaml2ui_roundtrip.ui'
        if not args.output:
            with open(output_path, 'w') as f:
                f.write(xml_text)
        verify_roundtrip(args.verify, output_path)
        if not args.output:
            import os
            os.unlink(output_path)


if __name__ == "__main__":
    main()
