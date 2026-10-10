"""Streaming CSV facts; no CRS or semantic interpretation is inferred."""
import csv
import itertools
import math
import os
import time


def profile_csv(path, delimiter=None, encoding="utf-8-sig", has_header=None, column_names=None):
    if not isinstance(has_header, bool):
        raise ValueError("CSV_HEADER_MODE_REQUIRED: specify has_header=true or false. For headerless data, column_names may name the columns without discarding the first record.")
    if column_names is not None and (not isinstance(column_names, list) or any(not isinstance(name, str) for name in column_names)):
        raise ValueError("column_names must be an array of strings")
    if has_header and column_names is not None:
        raise ValueError("column_names is only supported with has_header=false; headered CSV uses its actual column names")
    started = time.monotonic()
    before = os.stat(path)
    with open(path, "r", encoding=encoding, newline="") as stream:
        sample = stream.read(32768)
        stream.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error as exc:
                raise ValueError("CSV delimiter is ambiguous; specify delimiter explicitly") from exc
        if len(delimiter) != 1:
            raise ValueError("delimiter must be one character")
        reader = csv.reader(stream, delimiter=delimiter)
        first = next((values for values in reader if values), None)
        if first is None:
            raise ValueError("CSV contains no records")
        headers = first if has_header else (column_names if column_names is not None else [f"column_{index + 1}" for index in range(len(first))])
        headers = [name.strip() for name in headers]
        if len(headers) != len(first):
            raise ValueError(f"column_names has {len(headers)} entries; CSV has {len(first)} columns")
        if len(set(headers)) != len(headers) or any(not name for name in headers):
            raise ValueError("CSV requires unique, non-empty column headers or column_names")
        fields = {name: {"missing": 0, "numeric_count": 0, "non_numeric_count": 0, "non_finite_count": 0,
                         "min": None, "max": None, "value_counts": {}, "value_counts_complete": True} for name in headers}
        rows, preview = 0, []
        records = reader if has_header else itertools.chain([first], reader)
        for values in records:
            line = reader.line_num
            if time.monotonic() - started > 15:
                raise ValueError("CSV inspection exceeded 15 seconds; no complete statistics reported. Partition or inspect the file explicitly.")
            if not values:
                continue
            if len(values) != len(headers):
                raise ValueError(f"CSV row {line} has {len(values)} values; expected {len(headers)}")
            rows += 1
            if len(preview) < 5:
                preview.append(dict(zip(headers, values)))
            for name, value in zip(headers, values):
                field = fields[name]
                stripped = value.strip()
                counts = field["value_counts"]
                if field["value_counts_complete"]:
                    if stripped not in counts and len(counts) >= 50:
                        field["value_counts_complete"] = False
                        field["value_counts"] = {}  # do not imply partial counts are a distribution
                    else:
                        counts[stripped] = counts.get(stripped, 0) + 1
                if not stripped:
                    field["missing"] += 1
                    continue
                try:
                    number = float(stripped)
                except ValueError:
                    field["non_numeric_count"] += 1
                    continue
                if not math.isfinite(number):
                    field["non_finite_count"] += 1
                    continue
                field["numeric_count"] += 1
                field["min"] = number if field["min"] is None else min(number, field["min"])
                field["max"] = number if field["max"] is None else max(number, field["max"])
    after = os.stat(path)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("CSV changed during inspection; repeat before using these statistics")
    return {"path": os.path.abspath(path), "size_bytes": after.st_size, "mtime_ns": after.st_mtime_ns,
            "delimiter": delimiter, "encoding": encoding, "has_header": has_header, "row_count": rows, "columns": headers,
            "fields": fields, "preview": preview, "complete": True,
            "note": "Facts from the selected file only. Numeric parsing uses decimal dot; CRS, units and column roles require explicit confirmation."}
