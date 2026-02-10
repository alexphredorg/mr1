#!/usr/bin/env python3
"""Convert Qt Designer .ui (XML) to simplified YAML.

Usage:
    python3 ui2yaml.py qtdragon_hd_mr1.ui [-o qtdragon_hd_mr1.yaml]

Uses only stdlib — no PyYAML dependency. Custom YAML emitter gives full
control over formatting and compaction.
"""

import argparse
import sys
import xml.etree.ElementTree as ET


# ── Default values to drop ──────────────────────────────────────────────

DEFAULT_PROPS = {
    # sizePolicy
    "sizePolicy": "Preferred/Preferred",
    # sizes
    "minimumSize": "0x0",
    "maximumSize": "16777215x16777215",
    "baseSize": "0x0",
    # booleans
    "checkable": False,
    "checked": False,
    "flat": False,
    "autoFillBackground": False,
    "readOnly": False,
    "editable": False,
    "enabled": True,
    # stretch
    "horstretch": 0,
    "verstretch": 0,
}


# ── XML value extraction helpers ────────────────────────────────────────

def parse_size(elem):
    """<size><width>W</width><height>H</height></size> → 'WxH'"""
    w = elem.findtext("width", "0")
    h = elem.findtext("height", "0")
    return f"{w}x{h}"


def parse_rect(elem):
    """<rect><x>X</x><y>Y</y><width>W</width><height>H</height></rect> → 'WxH+X+Y'"""
    x = elem.findtext("x", "0")
    y = elem.findtext("y", "0")
    w = elem.findtext("width", "0")
    h = elem.findtext("height", "0")
    return f"{w}x{h}+{x}+{y}"


def parse_sizepolicy(elem):
    """<sizepolicy hsizetype='..' vsizetype='..'>...</sizepolicy> → 'H/V'"""
    h = elem.get("hsizetype", "Preferred")
    v = elem.get("vsizetype", "Preferred")
    return f"{h}/{v}"


def parse_color(elem):
    """<color [alpha='A']><red>R</red>...</color> → '#rrggbb' or 'rgba(r,g,b,a)'"""
    r = int(elem.findtext("red", "0"))
    g = int(elem.findtext("green", "0"))
    b = int(elem.findtext("blue", "0"))
    alpha = elem.get("alpha")
    if alpha is not None:
        return f"rgba({r},{g},{b},{alpha})"
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_font(elem):
    """<font>...</font> → compact string like 'Lato 10pt bold italic'"""
    parts = []
    family = elem.findtext("family")
    if family:
        parts.append(family)
    ps = elem.findtext("pointsize")
    if ps:
        parts.append(f"{ps}pt")
    if elem.findtext("bold") == "true":
        parts.append("bold")
    elif elem.findtext("weight"):
        w = elem.findtext("weight")
        if w != "50":  # 50 is normal weight
            parts.append(f"weight={w}")
    if elem.findtext("italic") == "true":
        parts.append("italic")
    if elem.findtext("underline") == "true":
        parts.append("underline")
    if elem.findtext("strikeout") == "true":
        parts.append("strikeout")
    if not parts:
        return ""
    return " ".join(parts)


def parse_iconset(elem):
    """<iconset resource='...'><normaloff>path</normaloff>...</iconset> → dict or path"""
    result = {}
    res = elem.get("resource")
    if res:
        result["resource"] = res
    # Icon states: normaloff, normalon, disabledoff, disabledon, activeoff, activeon, selectedoff, selectedon
    states = ["normaloff", "normalon", "disabledoff", "disabledon",
              "activeoff", "activeon", "selectedoff", "selectedon"]
    found_states = {}
    for state in states:
        sub = elem.find(state)
        if sub is not None and sub.text and sub.text.strip():
            found_states[state] = sub.text.strip()
    if len(found_states) == 1 and "normaloff" in found_states:
        # Simple case — just one icon path
        path = found_states["normaloff"]
        if res:
            return {"resource": res, "path": path}
        return path
    if found_states:
        result.update(found_states)
    return result if result else elem.text or ""


def clean_double(text):
    """'0.200000000000000' → 0.2"""
    try:
        val = float(text)
        # Format cleanly — no trailing zeros
        if val == int(val):
            return int(val)
        return val
    except (ValueError, TypeError):
        return text


def parse_property_value(prop_elem):
    """Extract the value from a <property> child element.

    Returns (value, value_type_tag) — value_type_tag used for special handling.
    """
    child = None
    for c in prop_elem:
        child = c
        break
    if child is None:
        # Property with direct text (rare)
        return prop_elem.text or "", "text"

    tag = child.tag

    if tag == "string":
        text = child.text or ""
        return text, "string"
    elif tag == "number":
        text = child.text or "0"
        try:
            return int(text), "number"
        except ValueError:
            return text, "number"
    elif tag == "double":
        return clean_double(child.text), "double"
    elif tag == "bool":
        return child.text == "true", "bool"
    elif tag == "enum":
        return child.text or "", "enum"
    elif tag == "set":
        return child.text or "", "set"
    elif tag == "rect":
        return parse_rect(child), "rect"
    elif tag == "size":
        return parse_size(child), "size"
    elif tag == "sizepolicy":
        return parse_sizepolicy(child), "sizepolicy"
    elif tag == "color":
        return parse_color(child), "color"
    elif tag == "font":
        return parse_font(child), "font"
    elif tag == "iconset":
        return parse_iconset(child), "iconset"
    elif tag == "pixmap":
        return child.text.strip() if child.text else "", "pixmap"
    elif tag == "url":
        url_text = child.findtext("string", "")
        return url_text, "url"
    elif tag == "stringlist":
        items = [s.text or "" for s in child.findall("string")]
        return items, "stringlist"
    elif tag == "char":
        code = child.findtext("unicode")
        return f"U+{code}" if code else "", "char"
    elif tag == "cursor":
        return int(child.text) if child.text else 0, "cursor"
    elif tag == "cursorShape":
        return child.text or "", "cursorShape"
    elif tag == "locale":
        lang = child.get("language", "")
        country = child.get("country", "")
        return f"{lang}/{country}", "locale"
    else:
        # Fallback — return text content
        return child.text or "", tag


# ── Widget/layout tree processing ───────────────────────────────────────

def process_properties(elem):
    """Extract all <property> children into a dict, applying compactions.

    Also handles margin collapsing and min/max → fixedSize.
    """
    props = {}
    margin_names = ("leftMargin", "topMargin", "rightMargin", "bottomMargin")
    margins = {}

    for prop in elem.findall("property"):
        name = prop.get("name", "")
        stdset = prop.get("stdset")
        value, vtype = parse_property_value(prop)

        # Track margins separately for collapsing
        if name in margin_names:
            margins[name] = value
            continue

        # Mark custom properties with * suffix
        key = f"{name}*" if stdset == "0" else name

        # Drop defaults
        if name in DEFAULT_PROPS and value == DEFAULT_PROPS[name]:
            continue

        # Drop empty strings
        if isinstance(value, str) and value == "" and name != "text":
            continue

        props[key] = value

    # Collapse margins
    if margins:
        vals = [margins.get(m, 0) for m in margin_names]
        if all(v == vals[0] for v in vals):
            props["margins"] = vals[0]
        else:
            props["margins"] = vals

    # Collapse min/max into fixedSize
    min_size = props.get("minimumSize")
    max_size = props.get("maximumSize")
    if min_size and max_size and min_size == max_size:
        props["fixedSize"] = min_size
        del props["minimumSize"]
        del props["maximumSize"]

    return props


def process_attributes(elem):
    """Extract all <attribute> children into a dict."""
    attrs = {}
    for attr in elem.findall("attribute"):
        name = attr.get("name", "")
        value, vtype = parse_property_value(attr)
        # Ignore empty values
        if isinstance(value, str) and value == "":
            continue
        attrs[name] = value
    return attrs


def process_widget(elem):
    """Convert a <widget> XML element to a dict."""
    result = {}
    cls = elem.get("class", "")
    name = elem.get("name", "")
    native = elem.get("native")

    result["class"] = cls
    if name:
        result["name"] = name
    if native == "true":
        result["native"] = True

    # Properties
    props = process_properties(elem)
    if props:
        result["properties"] = props

    # Attributes (e.g., tab titles, buttonGroup, table header settings)
    attrs = process_attributes(elem)
    if attrs:
        result["attributes"] = attrs

    # Children: widgets, layouts, zorder
    children = []
    for child in elem:
        if child.tag == "widget":
            children.append({"widget": process_widget(child)})
        elif child.tag == "layout":
            children.append({"layout": process_layout(child)})
        elif child.tag == "action":
            children.append({"action": process_widget(child)})
        elif child.tag == "addaction":
            children.append({"addaction": child.get("name", "")})

    if children:
        result["children"] = children

    # Z-order
    zorder = [z.text for z in elem.findall("zorder") if z.text]
    if zorder:
        result["zorder"] = zorder

    return result


def process_layout(elem):
    """Convert a <layout> XML element to a dict."""
    result = {}
    cls = elem.get("class", "")
    name = elem.get("name", "")

    result["class"] = cls
    if name:
        result["name"] = name

    # Properties
    props = process_properties(elem)
    if props:
        result["properties"] = props

    # Items
    items = []
    for item_elem in elem.findall("item"):
        item = process_layout_item(item_elem)
        if item:
            items.append(item)

    if items:
        result["items"] = items

    return result


def process_layout_item(item_elem):
    """Convert a layout <item> to a dict.

    Grid items carry row/column/rowspan/colspan attributes.
    Items may have an alignment attribute.
    """
    item = {}

    # Grid positioning
    row = item_elem.get("row")
    col = item_elem.get("column")
    rowspan = item_elem.get("rowspan")
    colspan = item_elem.get("colspan")
    alignment = item_elem.get("alignment")

    if row is not None:
        item["row"] = int(row)
    if col is not None:
        item["column"] = int(col)
    if rowspan is not None and rowspan != "1":
        item["rowspan"] = int(rowspan)
    if colspan is not None and colspan != "1":
        item["colspan"] = int(colspan)
    if alignment:
        item["alignment"] = alignment

    # Content — widget, layout, or spacer
    widget = item_elem.find("widget")
    layout = item_elem.find("layout")
    spacer = item_elem.find("spacer")

    if widget is not None:
        item["widget"] = process_widget(widget)
    elif layout is not None:
        item["layout"] = process_layout(layout)
    elif spacer is not None:
        item["spacer"] = process_spacer(spacer)

    return item


def process_spacer(elem):
    """Convert a <spacer> element to a dict."""
    result = {}
    name = elem.get("name")
    if name:
        result["name"] = name
    props = process_properties(elem)
    if props:
        result["properties"] = props
    return result


# ── Top-level sections ──────────────────────────────────────────────────

def process_custom_widgets(root):
    """<customwidgets> → list of dicts."""
    section = root.find("customwidgets")
    if section is None:
        return []
    widgets = []
    for cw in section.findall("customwidget"):
        entry = {}
        cls = cw.findtext("class", "")
        extends = cw.findtext("extends", "")
        header = cw.findtext("header", "")
        container = cw.findtext("container")
        if cls:
            entry["class"] = cls
        if extends:
            entry["extends"] = extends
        if header:
            entry["header"] = header
        if container == "1":
            entry["container"] = True
        widgets.append(entry)
    return widgets


def process_resources(root):
    """<resources> → deduplicated list of locations."""
    section = root.find("resources")
    if section is None:
        return []
    seen = set()
    result = []
    for inc in section.findall("include"):
        loc = inc.get("location", "")
        if loc and loc not in seen:
            seen.add(loc)
            result.append(loc)
    return result


def process_connections(root):
    """<connections> → list of {sender, signal, receiver, slot}. Drops hints."""
    section = root.find("connections")
    if section is None:
        return []
    conns = []
    for conn in section.findall("connection"):
        entry = {
            "sender": conn.findtext("sender", ""),
            "signal": conn.findtext("signal", ""),
            "receiver": conn.findtext("receiver", ""),
            "slot": conn.findtext("slot", ""),
        }
        conns.append(entry)
    return conns


def process_slots(root):
    """<slots> → {signals: [...], slots: [...]}"""
    section = root.find("slots")
    if section is None:
        return None
    result = {}
    signals = [s.text for s in section.findall("signal") if s.text]
    slots = [s.text for s in section.findall("slot") if s.text]
    if signals:
        result["signals"] = signals
    if slots:
        result["slots"] = slots
    return result if result else None


def process_button_groups(root):
    """<buttongroups> → list of names."""
    section = root.find("buttongroups")
    if section is None:
        return []
    return [bg.get("name", "") for bg in section.findall("buttongroup") if bg.get("name")]


# ── YAML emitter ────────────────────────────────────────────────────────

def yaml_needs_quoting(s):
    """Does string s need quoting in YAML?"""
    if not isinstance(s, str):
        return False
    if s == "":
        return True
    # Strings that look like booleans, numbers, or null
    lower = s.lower()
    if lower in ("true", "false", "yes", "no", "on", "off", "null", "~"):
        return True
    # Strings starting with special chars
    if s[0] in ('{', '}', '[', ']', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '#', ','):
        return True
    # Strings containing colon-space, hash-space, or newlines
    if ': ' in s or ' #' in s or '\n' in s:
        return True
    # Strings that could be parsed as numbers
    try:
        float(s)
        return True
    except ValueError:
        pass
    return False


def yaml_format_value(value, indent=0):
    """Format a single YAML value (scalar, list, or dict)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        # Clean float formatting
        if value == int(value):
            return str(int(value))
        # Remove trailing zeros but keep at least one decimal
        s = f"{value:.15g}"
        return s
    elif isinstance(value, str):
        if yaml_needs_quoting(value):
            # Use double quotes, escape embedded quotes
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        return value
    elif isinstance(value, list):
        return None  # Handled by caller as block list
    elif isinstance(value, dict):
        return None  # Handled by caller as block map
    else:
        return str(value)


def yaml_emit(data, indent=0, stream=None):
    """Emit a data structure as YAML text."""
    if stream is None:
        import io
        stream = io.StringIO()
        yaml_emit(data, indent, stream)
        return stream.getvalue()

    prefix = "  " * indent

    if isinstance(data, dict):
        if not data:
            stream.write("{}\n")
            return
        for key, value in data.items():
            key_str = yaml_format_value(key) if yaml_needs_quoting(str(key)) else str(key)

            if isinstance(value, dict):
                stream.write(f"{prefix}{key_str}:\n")
                yaml_emit(value, indent + 1, stream)
            elif isinstance(value, list):
                if not value:
                    stream.write(f"{prefix}{key_str}: []\n")
                elif _is_simple_list(value):
                    # Inline short simple lists
                    items = ", ".join(yaml_format_value(v) for v in value)
                    stream.write(f"{prefix}{key_str}: [{items}]\n")
                else:
                    stream.write(f"{prefix}{key_str}:\n")
                    _emit_list(value, indent + 1, stream)
            else:
                formatted = yaml_format_value(value)
                stream.write(f"{prefix}{key_str}: {formatted}\n")

    elif isinstance(data, list):
        _emit_list(data, indent, stream)
    else:
        formatted = yaml_format_value(data)
        stream.write(f"{prefix}{formatted}\n")


def _is_simple_list(lst):
    """Is this a list of simple scalars that fits on one line?"""
    if len(lst) > 6:
        return False
    for item in lst:
        if isinstance(item, (dict, list)):
            return False
        s = yaml_format_value(item)
        if s is None or len(str(s)) > 40:
            return False
    return True


def _emit_list(lst, indent, stream):
    """Emit a YAML list."""
    prefix = "  " * indent
    for item in lst:
        if isinstance(item, dict):
            # Check if it's a single-key dict wrapping another dict (common pattern)
            keys = list(item.keys())
            if len(keys) == 1 and isinstance(item[keys[0]], dict):
                key = keys[0]
                key_str = yaml_format_value(key) if yaml_needs_quoting(str(key)) else str(key)
                stream.write(f"{prefix}- {key_str}:\n")
                yaml_emit(item[key], indent + 2, stream)
            elif len(keys) == 1 and not isinstance(item[keys[0]], (dict, list)):
                key = keys[0]
                key_str = yaml_format_value(key) if yaml_needs_quoting(str(key)) else str(key)
                val_str = yaml_format_value(item[key])
                stream.write(f"{prefix}- {key_str}: {val_str}\n")
            else:
                # Multi-key dict item
                first = True
                for key, value in item.items():
                    key_str = yaml_format_value(key) if yaml_needs_quoting(str(key)) else str(key)
                    if first:
                        if isinstance(value, (dict, list)):
                            stream.write(f"{prefix}- {key_str}:\n")
                            if isinstance(value, dict):
                                yaml_emit(value, indent + 2, stream)
                            else:
                                _emit_list(value, indent + 2, stream)
                        else:
                            val_str = yaml_format_value(value)
                            stream.write(f"{prefix}- {key_str}: {val_str}\n")
                        first = False
                    else:
                        inner_prefix = "  " * (indent + 1)
                        if isinstance(value, (dict, list)):
                            stream.write(f"{inner_prefix}{key_str}:\n")
                            if isinstance(value, dict):
                                yaml_emit(value, indent + 2, stream)
                            else:
                                _emit_list(value, indent + 2, stream)
                        else:
                            val_str = yaml_format_value(value)
                            stream.write(f"{inner_prefix}{key_str}: {val_str}\n")
        elif isinstance(item, list):
            stream.write(f"{prefix}-\n")
            _emit_list(item, indent + 1, stream)
        else:
            val_str = yaml_format_value(item)
            stream.write(f"{prefix}- {val_str}\n")


# ── Main conversion ────────────────────────────────────────────────────

def convert_ui_to_yaml(ui_path):
    """Parse a .ui file and return the YAML data structure."""
    tree = ET.parse(ui_path)
    root = tree.getroot()

    data = {}

    # Top-level metadata
    ui_version = root.get("version", "4.0")
    data["ui_version"] = ui_version

    author = root.findtext("author")
    if author:
        data["author"] = author

    cls = root.findtext("class")
    if cls:
        data["class"] = cls

    # Main widget tree
    main_widget = root.find("widget")
    if main_widget is not None:
        data["widget"] = process_widget(main_widget)

    # Custom widgets
    custom_widgets = process_custom_widgets(root)
    if custom_widgets:
        data["customwidgets"] = custom_widgets

    # Resources (deduplicated)
    resources = process_resources(root)
    if resources:
        data["resources"] = resources

    # Connections (without hints)
    connections = process_connections(root)
    if connections:
        data["connections"] = connections

    # Slots
    slots = process_slots(root)
    if slots:
        data["slots"] = slots

    # Button groups
    button_groups = process_button_groups(root)
    if button_groups:
        data["buttongroups"] = button_groups

    return data


def count_elements(root, tag):
    """Count elements with a given tag in the XML tree."""
    return sum(1 for _ in root.iter(tag))


def verify(ui_path, yaml_data):
    """Print verification stats comparing XML source to YAML output."""
    tree = ET.parse(ui_path)
    root = tree.getroot()

    xml_widgets = count_elements(root, "widget")
    xml_layouts = count_elements(root, "layout")
    xml_connections = len(root.findall(".//connections/connection"))
    xml_custom_widgets = len(root.findall(".//customwidgets/customwidget"))

    def count_yaml_key(data, key):
        """Recursively count occurrences of a key in nested dicts/lists."""
        count = 0
        if isinstance(data, dict):
            for k, v in data.items():
                if k == key:
                    count += 1
                count += count_yaml_key(v, key)
        elif isinstance(data, list):
            for item in data:
                count += count_yaml_key(item, key)
        return count

    yaml_widgets = count_yaml_key(yaml_data, "widget")
    # Subtract 1 for the top-level "widget" key which wraps the root widget
    # Actually, count_yaml_key counts dict keys, each representing one widget
    yaml_layouts = count_yaml_key(yaml_data, "layout")
    yaml_connections = len(yaml_data.get("connections", []))
    yaml_custom_widgets = len(yaml_data.get("customwidgets", []))

    print(f"\n── Verification ──", file=sys.stderr)
    print(f"  Widgets:        XML={xml_widgets:4d}  YAML={yaml_widgets:4d}  {'OK' if xml_widgets == yaml_widgets else 'MISMATCH'}", file=sys.stderr)
    print(f"  Layouts:        XML={xml_layouts:4d}  YAML={yaml_layouts:4d}  {'OK' if xml_layouts == yaml_layouts else 'MISMATCH'}", file=sys.stderr)
    print(f"  Connections:    XML={xml_connections:4d}  YAML={yaml_connections:4d}  {'OK' if xml_connections == yaml_connections else 'MISMATCH'}", file=sys.stderr)
    print(f"  Custom widgets: XML={xml_custom_widgets:4d}  YAML={yaml_custom_widgets:4d}  {'OK' if xml_custom_widgets == yaml_custom_widgets else 'MISMATCH'}", file=sys.stderr)

    all_ok = (xml_widgets == yaml_widgets and
              xml_layouts == yaml_layouts and
              xml_connections == yaml_connections and
              xml_custom_widgets == yaml_custom_widgets)
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Convert Qt .ui XML to simplified YAML")
    parser.add_argument("input", help="Path to .ui file")
    parser.add_argument("-o", "--output", help="Output .yaml file (default: stdout)")
    parser.add_argument("--no-verify", action="store_true", help="Skip verification")
    args = parser.parse_args()

    yaml_data = convert_ui_to_yaml(args.input)

    if not args.no_verify:
        verify(args.input, yaml_data)

    yaml_text = yaml_emit(yaml_data)

    if args.output:
        with open(args.output, "w") as f:
            f.write(yaml_text)
        print(f"\nWrote {len(yaml_text):,} bytes to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(yaml_text)


if __name__ == "__main__":
    main()
