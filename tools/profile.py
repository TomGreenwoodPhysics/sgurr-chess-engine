"""Sampling profiler for the engine on Windows.

Suspends the search thread about every millisecond, reads its instruction
pointer, and maps addresses to functions and source lines with llvm-symbolizer
(DWARF, inlined frames too). Profile the PGO and ThinLTO release build: a build
without LTO overstates call costs that the release build inlines away.

    python tools/profile.py sgurr_cpp/sgr.exe bench 13

METHODOLOGY section 11 describes how it is used."""
import collections, ctypes, ctypes.wintypes as wt, struct, subprocess, sys, time

exe, args = sys.argv[1], sys.argv[2:]
SYMBOLIZER = 'C:/msys64/clang64/bin/llvm-symbolizer.exe'
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
winmm = ctypes.WinDLL('winmm')

class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG),
                ('dwFlags', wt.DWORD)]
class MODULEENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('th32ModuleID', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('GlblcntUsage', wt.DWORD), ('ProccntUsage', wt.DWORD), ('modBaseAddr', ctypes.c_void_p),
                ('modBaseSize', wt.DWORD), ('hModule', wt.HMODULE), ('szModule', ctypes.c_char * 256),
                ('szExePath', ctypes.c_char * 260)]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenThread.restype = wt.HANDLE

def threads(pid):
    snap = k32.CreateToolhelp32Snapshot(0x4, 0)
    te = THREADENTRY32(); te.dwSize = ctypes.sizeof(te); out = []
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid: out.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap); return out

def module(pid):
    snap = k32.CreateToolhelp32Snapshot(0x8, pid)
    me = MODULEENTRY32(); me.dwSize = ctypes.sizeof(me)
    k32.Module32First(snap, ctypes.byref(me)); k32.CloseHandle(snap)
    return me.modBaseAddr, me.modBaseSize

def image_base(path):
    b = open(path, 'rb').read(4096)
    pe = struct.unpack_from('<I', b, 0x3C)[0]
    return struct.unpack_from('<Q', b, pe + 48)[0]   # PE32+ OptionalHeader.ImageBase

proc = subprocess.Popen([exe] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.3)
base, size = module(proc.pid)
handles = [k32.OpenThread(0x0002 | 0x0008 | 0x0040, False, t) for t in threads(proc.pid)]
raw = (ctypes.c_char * (1232 + 16))()
addr = (ctypes.addressof(raw) + 15) & ~15
ctx = (ctypes.c_char * 1232).from_address(addr)
per_thread = [collections.Counter() for _ in handles]
winmm.timeBeginPeriod(1)
t0 = time.time()
while proc.poll() is None:
    for ti, h in enumerate(handles):
        if k32.SuspendThread(h) == 0xFFFFFFFF: continue
        struct.pack_into('<I', ctx, 0x30, 0x00100001)   # CONTEXT_AMD64 | CONTEXT_CONTROL
        if k32.GetThreadContext(h, ctypes.c_void_p(addr)):
            per_thread[ti][struct.unpack_from('<Q', ctx, 0xF8)[0]] += 1
        k32.ResumeThread(h)
    time.sleep(0.001)
winmm.timeEndPeriod(1)
elapsed = time.time() - t0

def in_bin(c): return sum(n for a, n in c.items() if base <= a < base + size)
samples = max(per_thread, key=in_bin)       # the search thread; the rest idle in ntdll
total = sum(samples.values())
outside = total - in_bin(samples)
ib = image_base(exe)
addrs = list(samples)
query = '\n'.join(hex(a - base + ib) for a in addrs)
out = subprocess.run([SYMBOLIZER, f'--obj={exe}', '--inlining', '--functions=short', '--basenames'],
                     input=query, capture_output=True, text=True).stdout
blocks = out.strip('\n').split('\n\n')

inner, outer, where = collections.Counter(), collections.Counter(), collections.Counter()
for a, blk in zip(addrs, blocks):
    ls = blk.split('\n')
    funcs, locs = ls[0::2], ls[1::2]
    n = samples[a]
    inner[funcs[0]] += n
    outer[funcs[-1]] += n
    where[f"{funcs[0]}  {locs[0] if locs else '?'}"] += n

print(f"{len(handles)} threads; search thread {total} samples over {elapsed:.1f}s; "
      f"{100 * outside / total:.1f}% of it inside Windows DLLs")

def show(title, c, k):
    print(f"\n{title}")
    for f, n in c.most_common(k):
        if 100 * n / total >= 0.3: print(f"  {100 * n / total:5.1f}%  {f}")

show("By innermost function:", inner, 25)
show("By enclosing non-inlined function:", outer, 16)
show("By source line of the innermost frame:", where, 30)
