#!/usr/bin/env python3
"""Diagnostic only: replace decoded x86 PAUSE instructions in a PRIVATE libgomp copy."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    source = args.source.resolve()
    if source == args.output.resolve():
        p.error("output must be a separate private copy")
    original = source.read_bytes()
    data = bytearray(original)
    addresses = []
    if platform.machine() == "x86_64":
        headers = subprocess.check_output(["objdump", "-h", str(source)], text=True)
        sections = []
        header_lines = headers.splitlines()
        for index, line in enumerate(header_lines):
            fields = line.split()
            if (len(fields) >= 7 and fields[0].isdigit() and index + 1 < len(header_lines)
                    and "CODE" in header_lines[index + 1] and "ALLOC" in header_lines[index + 1]):
                sections.append((fields[1], int(fields[3], 16), int(fields[2], 16), int(fields[5], 16)))
        disasm = subprocess.check_output(["objdump", "-d", str(source)], text=True)
        for line in disasm.splitlines():
            match = re.match(r"\s*([0-9a-f]+):\s+f3 90\s+pause\s*$", line)
            if not match:
                continue
            addr = int(match[1], 16)
            matching = [(vma, offset) for _, vma, size, offset in sections if vma <= addr < vma + size]
            if len(matching) != 1:
                raise RuntimeError(f"Ambiguous ELF section for {addr:x}")
            vma, offset = matching[0]
            pos = offset + addr - vma
            if data[pos:pos+2] != b"\xf3\x90":
                raise RuntimeError("Instruction bytes do not match")
            data[pos:pos+2] = b"\x90\x90"
            addresses.append({"virtual_address": hex(addr), "file_offset": pos})
        if not addresses:
            raise RuntimeError("No decoded PAUSE instructions found")
        differences = [i for i, (a, b) in enumerate(zip(original, data)) if a != b]
        if set(differences) != {a["file_offset"] for a in addresses}:
            raise RuntimeError("Unexpected byte differences")
    else:
        if platform.machine() != "aarch64":
            raise RuntimeError("Only x86-64 and ARM64 are supported")
        # ARM64 is a sham copy control: no PAUSE instruction exists to replace.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.chmod(0o755)
    report = {"diagnostic_only": True, "machine": platform.machine(), "source": str(source),
              "output": str(args.output.resolve()), "original_sha256": hashlib.sha256(original).hexdigest(),
              "modified_sha256": hashlib.sha256(data).hexdigest(), "replacements": addresses,
              "replacement": "PAUSE (f3 90) -> NOP NOP (90 90); ARM64 unchanged control"}
    args.output.with_suffix(".patch.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
