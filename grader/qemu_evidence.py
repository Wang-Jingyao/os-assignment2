"""Public host-side QEMU evidence collector. Serial text never creates evidence.

Uses a private Unix gdbstub socket, hardware PC breakpoint and RISC-V a0/memory
reads. The socket and this Python process exist outside guest memory.
"""
from pathlib import Path
import re
import socket
import struct
import subprocess
import time

SYMBOLS = {
 'correctness': ('lab5_std_c_fork::process::audit::proof_correctness', 4),
 'performance': ('lab5_std_c_fork::test::proof_performance', 2),
 'analysis': ('lab5_std_c_fork::spawn_analysis::proof_analysis', 11),
}

class RSP:
    def __init__(self, path, deadline):
        self.deadline = deadline
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(.5)
        self.sock.connect(str(path))
    def byte(self):
        while time.monotonic() < self.deadline:
            try:
                data = self.sock.recv(1)
                if not data: raise ValueError('QEMU exited before trusted checkpoint')
                return data
            except socket.timeout: pass
        raise ValueError('trusted checkpoint timeout')
    def packet(self):
        while self.byte() != b'$': pass
        data = bytearray()
        while True:
            b = self.byte()
            if b == b'#': break
            data.extend(b)
        checksum = self.byte() + self.byte()
        if sum(data) % 256 != int(checksum, 16): raise ValueError('gdbstub checksum mismatch')
        self.sock.sendall(b'+')
        # Decode RSP binary escaping and run-length encoding (register replies may use it).
        out = bytearray(); i = 0
        while i < len(data):
            c = data[i]; i += 1
            if c == ord('}'):
                c = data[i] ^ 0x20; i += 1
            elif c == ord('*'):
                out.extend(out[-1:] * (data[i] - 29)); i += 1; continue
            out.append(c)
        return out.decode('ascii')
    def command(self, value):
        data = value.encode('ascii')
        self.sock.sendall(b'$' + data + b'#' + ('%02x' % (sum(data) % 256)).encode())
        while True:
            ack = self.byte()
            if ack == b'+': break
            if ack == b'-': raise ValueError('gdbstub rejected packet')
        return self.packet()
    def close(self): self.sock.close()

def kernel_for_socket(path):
    """Read QEMU's actual -kernel argument, rather than guessing an old build file."""
    marker = 'path=' + str(path) + ','
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        try: args = (entry/'cmdline').read_bytes().decode().split('\0')
        except (OSError, UnicodeError): continue
        if not args or 'qemu-system-riscv64' not in args[0] or not any(marker in a for a in args): continue
        if '-kernel' not in args: continue
        kernel = Path(args[args.index('-kernel')+1])
        if not kernel.is_absolute(): kernel = (entry/'cwd').resolve()/kernel
        return kernel
    raise ValueError('could not identify the actual QEMU kernel')

def checkpoint_address(kernel, symbol):
    result = subprocess.run(['riscv64-linux-gnu-nm','--defined-only','-C',str(kernel)], capture_output=True, text=True, check=True)
    matches = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[1] in ('t','T') and re.fullmatch(re.escape(symbol) + r'(?:::h[0-9a-f]+)?', parts[2]):
            matches.append(int(parts[0],16))
    if len(matches) != 1: raise ValueError('missing or ambiguous private checkpoint: '+symbol)
    return matches[0]

def collect(kind, path, proc, deadline):
    path = Path(path)
    while not path.exists():
        if proc.poll() is not None: raise ValueError('command ended without a QEMU evidence channel')
        if time.monotonic() > deadline: raise ValueError('QEMU evidence startup timeout')
        time.sleep(.05)
    symbol, count = SYMBOLS[kind]
    kernel = kernel_for_socket(path)
    address = checkpoint_address(kernel, symbol)
    rsp = RSP(path, deadline)
    try:
        rsp.command('qSupported')
        rsp.command('?')
        if rsp.command(f'Z1,{address:x},4') != 'OK': raise ValueError('QEMU refused trusted breakpoint')
        stop = rsp.command('c')
        if not stop.startswith(('T05','S05')): raise ValueError('QEMU exited or stopped before trusted checkpoint: '+stop)
        registers = bytes.fromhex(rsp.command('g'))
        if len(registers) < 33*8: raise ValueError('invalid RISC-V register reply')
        pc = struct.unpack_from('<Q',registers,32*8)[0]
        if pc != address: raise ValueError('unexpected QEMU stop PC')
        pointer = struct.unpack_from('<Q',registers,10*8)[0]
        data = rsp.command(f'm{pointer:x},{count*8:x}')
        values = list(struct.unpack('<'+'Q'*count,bytes.fromhex(data)))
        if rsp.command(f'z1,{address:x},4') != 'OK': raise ValueError('could not remove breakpoint')
        if rsp.command('D') != 'OK': raise ValueError('could not resume QEMU after evidence')
        return {'kind':kind,'values':values,'checkpoint':symbol,'pc':hex(pc)}
    finally: rsp.close()
