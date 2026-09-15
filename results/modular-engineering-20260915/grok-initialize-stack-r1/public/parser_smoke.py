"""Pure parser smoke only; it never starts or attaches a process."""
from stack_capture import extract_module_labels

def main():
    raw = b"00 00000000`00000000 KERNEL32.DLL!Wait\n01 00000000`00000000 ntdll.dll!NtWait\n"
    assert extract_module_labels(raw) == ["kernel32.dll", "ntdll.dll"]

if __name__ == "__main__":
    main()
