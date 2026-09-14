"""Numeric Windows wait-chain metadata only; no memory or object-name output.

The caller runs this in a separate process with a four-second timeout because
synchronous WCT is not cancellable. Flags=0 never traverse another process.
ABI: microsoft/win32metadata generation/WinSDK/RecompiledIdlHeaders/um/wct.h.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
import sys


class ThreadEntry(C.Structure):
    _fields_ = [('size',W.DWORD),('usage',W.DWORD),('tid',W.DWORD),('pid',W.DWORD),
                ('base',W.LONG),('delta',W.LONG),('flags',W.DWORD)]


class Lock(C.Structure):
    _fields_ = [('name',W.WCHAR*128),('timeout',C.c_longlong),('alertable',W.BOOL)]


class Thread(C.Structure):
    _fields_ = [('pid',W.DWORD),('tid',W.DWORD),('wait_ms',W.DWORD),('context_switches',W.DWORD)]


class Detail(C.Union):
    _fields_ = [('lock',Lock),('thread',Thread)]


class Node(C.Structure):
    _fields_ = [('kind',W.DWORD),('status',W.DWORD),('detail',Detail)]


class IOCounters(C.Structure):
    _fields_ = [(k,C.c_ulonglong) for k in ('reads','writes','other','read_bytes','write_bytes','other_bytes')]


def snapshot(pid):
    if type(pid) is not int or pid <= 0 or os.name != 'nt': raise ValueError('Windows PID required')
    assert C.sizeof(Node) == 280 and C.sizeof(ThreadEntry) == 28
    kernel = C.WinDLL('kernel32',use_last_error=True); api=C.WinDLL('advapi32',use_last_error=True)
    def function(lib,name,args,result):
        fn=getattr(lib,name); fn.argtypes=args; fn.restype=result; return fn
    close=function(kernel,'CloseHandle',[W.HANDLE],W.BOOL)
    create=function(kernel,'CreateToolhelp32Snapshot',[W.DWORD,W.DWORD],W.HANDLE)
    first=function(kernel,'Thread32First',[W.HANDLE,C.POINTER(ThreadEntry)],W.BOOL)
    next_thread=function(kernel,'Thread32Next',[W.HANDLE,C.POINTER(ThreadEntry)],W.BOOL)
    open_process=function(kernel,'OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE)
    get_io=function(kernel,'GetProcessIoCounters',[W.HANDLE,C.POINTER(IOCounters)],W.BOOL)
    get_times=function(kernel,'GetProcessTimes',[W.HANDLE,*([C.POINTER(W.FILETIME)]*4)],W.BOOL)
    open_wct=function(api,'OpenThreadWaitChainSession',[W.DWORD,C.c_void_p],W.HANDLE)
    close_wct=function(api,'CloseThreadWaitChainSession',[W.HANDLE],None)
    get_wct=function(api,'GetThreadWaitChain',[W.HANDLE,C.c_size_t,W.DWORD,W.DWORD,
        C.POINTER(W.DWORD),C.POINTER(Node),C.POINTER(W.BOOL)],W.BOOL)
    report={'schema':'numeric-owned-process-wct-v1','pid':pid,'flags':0,'threads':[]}
    process=open_process(0x1000,False,pid)
    if process:
        try:
            io=IOCounters()
            if get_io(process,C.byref(io)):report['io']={k:getattr(io,k) for k,_ in io._fields_}
            times=[W.FILETIME() for _ in range(4)]
            if get_times(process,*(C.byref(t) for t in times)):
                values=[(t.dwHighDateTime<<32)|t.dwLowDateTime for t in times]
                report.update(creation_filetime=values[0],kernel_100ns=values[2],user_100ns=values[3])
        finally:close(process)
    else:report['process_error']=C.get_last_error()
    threads=[]; toolhelp=create(4,0)
    if toolhelp == C.c_void_p(-1).value:raise OSError(C.get_last_error(),'thread snapshot failed')
    try:
        entry=ThreadEntry();entry.size=C.sizeof(entry);more=first(toolhelp,C.byref(entry))
        while more:
            if entry.pid==pid:threads.append(entry.tid)
            more=next_thread(toolhelp,C.byref(entry))
    finally:close(toolhelp)
    report['thread_count']=len(threads);report['thread_limit']=64
    session=open_wct(0,None)
    if not session: report['wct_error']=C.get_last_error();return report
    try:
        for tid in sorted(threads)[:64]:
            count=W.DWORD(16); cycle=W.BOOL(); nodes=(Node*16)()
            ok=get_wct(session,0,0,tid,C.byref(count),nodes,C.byref(cycle))
            row={'tid':tid,'ok':bool(ok),'error':None if ok else C.get_last_error(),'nodes':[]}
            if ok:
                row['cycle']=bool(cycle.value)
                for node in nodes[:min(count.value,16)]:
                    item={'type':node.kind,'status':node.status}
                    if node.kind==8:
                        thread=node.detail.thread
                        item.update(pid=thread.pid,tid=thread.tid,wait_time_raw=thread.wait_ms,
                                    context_switches=thread.context_switches)
                    # Never serialize Lock.name, pointers, memory, logs or secrets.
                    row['nodes'].append(item)
            report['threads'].append(row)
    finally:close_wct(session)
    return report


if __name__=='__main__':
    print(json.dumps(snapshot(os.getpid() if sys.argv[1:] == ['--self'] else int(sys.argv[1]))))
