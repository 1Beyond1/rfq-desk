"""Windows process resource boundary; filesystem policy is separately cooperative."""
import os
import ctypes
from ctypes import wintypes

def contain(process):
    if os.name!='nt':raise OSError('This runner requires the tested Windows job-object backend')
    class Basic(ctypes.Structure):
        _fields_=[('UserTime',ctypes.c_int64),('JobTime',ctypes.c_int64),('Flags',wintypes.DWORD),('MinWS',ctypes.c_size_t),('MaxWS',ctypes.c_size_t),('Processes',wintypes.DWORD),('Affinity',ctypes.c_size_t),('Priority',wintypes.DWORD),('Scheduling',wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[('c'+str(i),ctypes.c_uint64) for i in range(6)]
    class Limits(ctypes.Structure):
        _fields_=[('Basic',Basic),('IO',IO),('ProcessMemory',ctypes.c_size_t),('JobMemory',ctypes.c_size_t),('PeakProcess',ctypes.c_size_t),('PeakJob',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateJobObjectW(None,None)
    limits=Limits();limits.Basic.Flags=0x100|0x2000|0x8;limits.Basic.Processes=1;limits.ProcessMemory=256*1024*1024
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,wintypes.HANDLE(int(process._handle))):
        error=ctypes.get_last_error();kernel.CloseHandle(handle);raise ctypes.WinError(error)
    return lambda:kernel.CloseHandle(handle)
