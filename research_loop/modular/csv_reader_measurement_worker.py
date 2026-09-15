"""Pinned CSV-reader measurement worker. It intentionally owns its parser."""
from __future__ import annotations

import argparse
import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def _decimal_sum(values: list[str]) -> str:
    parsed = []
    for value in values:
        if not value:
            continue
        if len(value) > 4096:
            raise ContractError("decimal cell exceeds worker bound")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ContractError("malformed decimal cell") from exc
        if not number.is_finite() or abs(number.as_tuple().exponent) > 2048:
            raise ContractError("non-finite or out-of-bound decimal cell")
        sign, digits, exponent = number.as_tuple()
        coefficient = int("".join(map(str, digits)) or "0") * (-1 if sign else 1)
        parsed.append((coefficient, exponent))
    if not parsed:
        return "0"
    low = min(exponent for _, exponent in parsed)
    total = sum(coefficient * (10 ** (exponent - low)) for coefficient, exponent in parsed)
    if total == 0:
        return "0"
    sign = "-" if total < 0 else ""
    text = str(abs(total))
    if low >= 0:
        return sign + text + "0" * low
    places = -low
    text = text.rjust(places + 1, "0")
    whole, fraction = text[:-places], text[-places:].rstrip("0")
    return sign + (whole or "0") + ("." + fraction if fraction else "")


def measure_specs(csv_path: Path, specs: tuple[FrozenRecord, ...]) -> FrozenRecord:
    if not specs:
        raise ContractError("one or more CSV specifications required")
    bodies = [spec.data() for spec in specs]
    requested = {body['column'] for body in bodies if body['operation'] != 'row_count'}
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as stream:
            rows = csv.reader(stream, strict=True)
            header = next(rows)
            if not header or any(not name.strip() for name in header) or len(set(header)) != len(header):
                raise ContractError("missing or duplicate CSV headers")
            if not requested <= set(header):
                raise ContractError("requested CSV column is absent")
            indices = {column: header.index(column) for column in requested}
            count, cells = 0, {column: [] for column in requested}
            for row in rows:
                if len(row) != len(header):
                    raise ContractError("malformed CSV row")
                count += 1
                for column, index in indices.items():
                    cells[column].append(row[index].strip())
    except (OSError, StopIteration, csv.Error) as exc:
        raise ContractError("malformed CSV input") from exc
    results = {}
    for spec, body in zip(specs, bodies, strict=True):
        if body["operation"] == "row_count":
            value = str(count)
        elif body["operation"] == "nonempty_count":
            value = str(sum(bool(cell) for cell in cells[body['column']]))
        else:
            value = _decimal_sum(cells[body['column']])
        results[body['original_key']] = {"schema": "admission-csv-measurement-result-v2", "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "spec_digest": spec.content_hash, "operation": body["operation"], "value": value, "matches_expected": value == body["expected"]}
    bundle = FrozenRecord.from_dict({'specifications': [spec.data() for spec in specs]})
    return FrozenRecord.from_dict({'schema': 'admission-csv-measurement-batch-result-v2', 'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'specifications_digest': bundle.content_hash, 'results': results})


def measure(csv_path: Path, spec: FrozenRecord) -> FrozenRecord:
    return FrozenRecord.from_dict(measure_specs(csv_path, (spec,)).data()['results'][spec.data()['original_key']])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--spec")
    parser.add_argument("--specs")
    args = parser.parse_args()
    if (args.spec is None) == (args.specs is None):
        raise ContractError('exactly one --spec or --specs is required')
    if args.spec is not None:
        print(measure(args.csv, FrozenRecord(args.spec)).encoded)
    else:
        bundle = FrozenRecord(args.specs).data()
        if set(bundle) != {'specifications'} or not isinstance(bundle['specifications'], list):
            raise ContractError('CSV specification bundle is malformed')
        print(measure_specs(args.csv, tuple(FrozenRecord.from_dict(value) for value in bundle['specifications'])).encoded)


if __name__ == "__main__":
    main()
