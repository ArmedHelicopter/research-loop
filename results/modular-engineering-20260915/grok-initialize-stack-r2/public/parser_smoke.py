from stack_capture import modules,frames
def main():
 raw=b'00000000`0000 00000000`0000 KERNEL32.DLL!Wait\n'
 assert frames(raw)==1 and modules(raw)==['kernel32.dll']
if __name__=='__main__': main()
