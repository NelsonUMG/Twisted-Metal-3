"""Execute the audited MIPS constructor slice, including branch/load delays.

This is a bounded instruction replay up to (not including) FUN800150FC. It
tests its exact input columns, not the GTE implementation or whole gameplay.
Unknown instructions, uninitialized reads and unexpected writes fail closed.
"""
import struct

import tm3_patch_projectile_basis_v1 as patch


def signed(value, bits=32):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits-1)) else value


def replay(blob, forward, old_right):
    stack, obj = 0x801FF000, 0x80167000
    regs = [0] + [0xA5000000 + n for n in range(1, 32)]
    regs[29], regs[19] = stack, obj
    memory, reads, writes, pcs = {}, [], [], []

    def put16(addr, value):
        memory[addr], memory[addr+1] = value & 255, (value >> 8) & 255

    def get16(addr):
        reads.append(addr)
        return memory[addr] | memory[addr+1] << 8

    for axis, value in enumerate(forward):
        put16(stack + 0x28 + 2*axis, value)
        put16(obj + 0x78 + 6*axis, value)
    for axis, value in enumerate(old_right):
        put16(obj + 0x74 + 6*axis, value)
    before = dict(memory)
    pc, next_pc, pending_load = patch.START, patch.START+4, None
    for _ in range(40):
        ins = patch.word(blob, pc)
        pcs.append(pc)
        op, rs, rt = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31
        imm = signed(ins & 0xffff, 16)
        successor, dest, value, new_load = next_pc+4, None, None, None
        # Reads use pre-load-commit registers; writes commit after old load.
        if op in (0x21, 0x25):
            raw = get16((regs[rs] + imm) & 0xffffffff)
            new_load = (rt, signed(raw,16) if op == 0x21 else raw)
        elif op == 0x29:
            addr = (regs[rs] + imm) & 0xffffffff
            if addr not in (obj+0x74, obj+0x7a, obj+0x80):
                raise ValueError(f'Unexpected write {addr:08X}')
            put16(addr, regs[rt]); writes.append(addr)
        elif op == 9:
            dest, value = rt, regs[rs] + imm
        elif op in (4, 5):
            equal = regs[rs] == regs[rt]
            if equal == (op == 4):
                successor = pc + 4 + 4*imm
        elif op == 0:
            rd, fn = (ins >> 11) & 31, ins & 63
            if ins == 0:
                pass
            elif fn in (0x21, 0x23, 0x25):
                dest = rd
                value = {0x21: lambda: regs[rs]+regs[rt],
                         0x23: lambda: regs[rs]-regs[rt],
                         0x25: lambda: regs[rs] | regs[rt]}[fn]()
            else:
                raise ValueError(f'Unsupported SPECIAL {ins:08X}')
        elif op == 3:
            if pc != patch.END or ins != 0x0C00543F:
                raise ValueError('Unexpected call')
            successor = 0x800150FC
            dest, value = 31, pc+8
        else:
            raise ValueError(f'Unsupported instruction {pc:08X} {ins:08X}')
        if pending_load and pending_load[0]:
            regs[pending_load[0]] = pending_load[1] & 0xffffffff
        if dest:
            regs[dest] = value & 0xffffffff
        regs[0] = 0
        pending_load = new_load
        pc, next_pc = next_pc, successor
        if pc == 0x800150FC:
            break
        if not patch.START <= pc <= patch.END + 4:
            raise ValueError('Escaped audited constructor slice')
    else:
        raise ValueError('Replay did not reach normalization call')
    if pending_load is not None:
        raise ValueError('Unexpected pending load at call')
    right = tuple(signed(get16(obj+0x74+6*i),16) for i in range(3))
    direction = tuple(signed(get16(obj+0x78+6*i),16) for i in range(3))
    return {'right': right, 'forward': direction, 'args': tuple(regs[4:7]),
            'pcs': pcs, 'reads': reads, 'writes': writes,
            'changed_addresses': sorted(a for a in memory if memory[a] != before.get(a)),
            'object': obj}


if __name__ == '__main__':
    import json
    original = patch.SOURCE.read_bytes()
    candidate, _, _ = patch.build(original)
    cases = {}
    for label, vector in [('captured_forward', (0,-2585,-3180)), ('z_axis_zero', (3000,0,0)),
                          ('vertical', (0,4096,0)), ('ordinary', (1234,-700,3500))]:
        cases[label] = {'forward': vector}
        for version, binary in [('original',original), ('candidate',candidate)]:
            cases[label][version] = [replay(binary,vector,p)['right']
                                    for p in [(111,222,333),(-400,500,-600)]]
    print(json.dumps({'scope': __doc__, 'cases': cases}, indent=2))
