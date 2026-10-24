#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

ORIGINAL_SHA256 = "2bb2a618889a057627a79d2a01cd53b83c6dbc12b9ea49a5f621b6179c5e8998"
MENU_SHA256 = "24fc2707d63ceaab857105c6b9bbf1e344054ace116c97d538c478310ba4d765"
LEGACY_NETWORK_SHA256 = "b61deb3f141c8b8329bcf811c51d41fb88fc4f0b75f83c42c7f7ff550650cba1"
FIXED_ROLE_NETWORK_SHA256 = "1a895c88df2176a2c9d345f8a9e07cd50bbb0996720bfcfe90128be5c5178d24"
BLOCKING_ROLE_NETWORK_SHA256 = "15d36e286eb3ceff3a7f03051894a4c1ebcfeb9eabf1f82bd73b49f21c64162c"
RETURNING_ROLE_NETWORK_SHA256 = "a101d2e151111faa21cb1d34ad84ac54e8bfcf78df3832cb9804a3195027088b"
PUMPED_ROLE_NETWORK_SHA256 = "263e8354f491b754fc4aa2bd946c839e569f0ed76b355189f088abcb1355f591"
PAYLOAD_LOAD_DELAY_FIXED_NETWORK_SHA256 = "e79b29564de0850bafc800f6d2b994bfb15ea086f9ebd2a79cf79d7829fc4c57"
ROLE_LOAD_DELAY_FIXED_NETWORK_SHA256 = "1541a04ee89046f0af8ab219c71eb9435ad067caf71e19fb1f1d456127b951e9"
OLD_MENU = b"LINKED GAME?"
NEW_MENU = b"MODO ONLINE?"
MENU_OFFSET = 0x78DBC

TEXT_ADDRESS = 0x80010000
FUNCTION_START = 0x80047728
FUNCTION_END = 0x80047D3C
READY_PROBE_START = 0x80047578
READY_PROBE_END = 0x800475A4
ROLE_SELECT_START = 0x80047DC0
ROLE_SELECT_END = 0x80047E80
TAIL_BRANCH_ADDRESS = 0x80047F18
TAIL_SUCCESS_ADDRESS = 0x80048060
MAILBOX_ADDRESS = 0x80047900
GAMEPLAY_BATCH_FUNCTION = 0x80047A00
GAMEPLAY_BATCH_FUNCTION_END = 0x80047D20
EXPANDED_RAM_PROBE = 0x80047C00
EXPANDED_RAM_PROBE_END = 0x80047C80
EXPANDED_RAM_TEST_ADDRESS = 0x80F00000
DRAM_CONTROL_ADDRESS = 0xBF801060
GAMEPLAY_BATCH_PATCH_START = 0x8003AA90
GAMEPLAY_BATCH_PATCH_END = 0x8003AB28
MAILBOX_MAGIC = 0x4F334D54  # bytes: TM3O
MAILBOX_VERSION = 5
MAILBOX_COMMAND_ROLE = 1
MAILBOX_COMMAND_TRANSFER = 2
MAILBOX_COMMAND_BATCH_TRANSFER = 3
MAILBOX_HEADER_SIZE = 112
MAX_TRANSFER = 64 * 1024
WAITING_CALLBACK_CALLS = (0x80047EA0, 0x80047EB8)

REG = {
    "zero": 0, "v0": 2, "v1": 3,
    "a0": 4, "a1": 5, "a2": 6, "a3": 7,
    "t0": 8, "t1": 9, "t2": 10, "t3": 11,
    "t4": 12, "t5": 13, "t6": 14, "t7": 15,
    "s0": 16, "s1": 17, "s4": 20, "s6": 22,
    "t8": 24, "t9": 25, "sp": 29, "ra": 31,
}


def r_type(rs: int, rt: int, rd: int, shift: int, function: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shift << 6) | function


def i_type(opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def j_type(opcode: int, target: int) -> int:
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def branch_word(opcode: int, rs: int, rt: int, source: int, target: int) -> int:
    delta = target - (source + 4)
    if delta % 4:
        raise ValueError("salto no alineado")
    immediate = delta // 4
    if not -0x8000 <= immediate <= 0x7FFF:
        raise ValueError("salto fuera de rango")
    return i_type(opcode, rs, rt, immediate)


class Assembler:
    def __init__(self, address: int):
        self.address = address
        self.words: list[int] = []
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, int, int, int, str]] = []

    def emit(self, word: int) -> None:
        self.words.append(word)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"etiqueta duplicada: {name}")
        self.labels[name] = self.address + len(self.words) * 4

    def branch(self, opcode: int, rs: int, rt: int, label: str) -> None:
        index = len(self.words)
        self.fixups.append((index, opcode, rs, rt, label))
        self.emit(0)

    def resolve(self) -> bytes:
        for index, opcode, rs, rt, label in self.fixups:
            target = self.labels[label]
            source = self.address + index * 4
            delta = target - (source + 4)
            if delta % 4:
                raise ValueError(f"salto no alineado a {label}")
            immediate = delta // 4
            if not -0x8000 <= immediate <= 0x7FFF:
                raise ValueError(f"salto fuera de rango a {label}")
            self.words[index] = i_type(opcode, rs, rt, immediate)
        return b"".join(struct.pack("<I", word) for word in self.words)


def build_stub(mailbox_version: int = MAILBOX_VERSION) -> bytes:
    z, v0 = REG["zero"], REG["v0"]
    a0, a1, a2, a3 = (REG[name] for name in ("a0", "a1", "a2", "a3"))
    t0, t1, t2 = (REG[name] for name in ("t0", "t1", "t2"))
    ra = REG["ra"]
    asm = Assembler(FUNCTION_START)
    nop = 0
    sp = REG["sp"]
    # The two post-vehicle transfers run inside the SIO/menu routine, which
    # keeps the original 0x800D3280 callback table in s1. Save ra because the
    # callback uses jalr and this stub must still return to its caller.
    asm.emit(i_type(0x09, sp, sp, -16))
    asm.emit(i_type(0x2B, sp, a2, 0))
    asm.emit(i_type(0x2B, sp, a3, 4))
    asm.emit(i_type(0x2B, sp, ra, 12))

    # v5 publica punteros a los buffers reales de RAM. El frontend valida los
    # rangos y puede transportar hasta 64 KiB sin copiar byte a byte en MIPS.
    asm.emit(i_type(0x0F, z, t0, MAX_TRANSFER >> 16))      # t0=65536
    asm.emit(r_type(t0, a1, t1, 0, 0x2B))                 # sltu t1,t0,a1
    asm.branch(0x05, t1, z, "failure")                    # a1>64 KiB
    asm.emit(nop)
    asm.emit(r_type(t0, a3, t1, 0, 0x2B))
    asm.branch(0x05, t1, z, "failure")                    # a3>64 KiB
    asm.emit(nop)

    # t0 = mailbox dentro del cuerpo SIO reemplazado.
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x0F, z, t1, MAILBOX_MAGIC >> 16))
    asm.emit(i_type(0x0D, t1, t1, MAILBOX_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, t0, t1, 0))                     # magic
    asm.emit(i_type(0x09, z, t1, mailbox_version))
    asm.emit(i_type(0x29, t0, t1, 4))                     # version
    asm.emit(i_type(0x09, z, t1, MAILBOX_COMMAND_TRANSFER))
    asm.emit(i_type(0x29, t0, t1, 8))                     # command
    asm.emit(i_type(0x2B, t0, z, 12))                     # sequence la asigna NetBridge
    asm.emit(i_type(0x2B, t0, a1, 16))                    # sendSize
    asm.emit(i_type(0x2B, t0, a3, 20))                    # recvCapacity
    asm.emit(i_type(0x2B, t0, z, 24))                     # recvSize
    asm.emit(i_type(0x2B, t0, ra, 28))                    # callSite
    asm.emit(i_type(0x2B, t0, a0, 32))                    # sendAddress
    asm.emit(i_type(0x2B, t0, a2, 36))                    # recvAddress
    asm.emit(i_type(0x2B, t0, z, 40))                     # sin segmentos batch
    asm.emit(i_type(0x2B, t0, z, 44))

    # Publica status=1 al final y espera la respuesta del hilo del frontend.
    asm.emit(i_type(0x09, z, t1, 1))
    asm.emit(i_type(0x29, t0, t1, 6))
    asm.label("wait_loop")
    # The game redraws WAITING FOR OTHER CONSOLE by calling s1[2]. During the
    # vehicle-confirmation transfers, unlike the initial role loop, LinkTransfer
    # owns the wait. Pump that callback only at its two verified call sites.
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x25, t0, t1, 6))                     # lhu t1,status
    asm.emit(i_type(0x09, z, t2, 3))
    asm.branch(0x04, t1, t2, "response_ready")
    asm.emit(nop)
    asm.emit(i_type(0x09, z, t2, 4))
    asm.branch(0x04, t1, t2, "failure")
    asm.emit(nop)
    asm.emit(i_type(0x23, t0, t1, 28))                    # callSite
    asm.emit(i_type(0x0F, z, t2, 0x8004))
    asm.emit(i_type(0x0D, t2, t2, WAITING_CALLBACK_CALLS[0] & 0xFFFF))
    asm.branch(0x04, t1, t2, "pump_waiting")
    asm.emit(nop)
    asm.emit(i_type(0x09, t2, t2, WAITING_CALLBACK_CALLS[1] - WAITING_CALLBACK_CALLS[0]))
    asm.branch(0x04, t1, t2, "pump_waiting")
    asm.emit(nop)
    # Other transfers stay idle here; only the verified pre-game menu calls
    # have a valid callback table in s1.
    asm.branch(0x04, z, z, "wait_loop")
    asm.emit(nop)

    asm.label("pump_waiting")
    asm.emit(i_type(0x23, REG["s1"], v0, 8))              # callback table +8
    asm.emit(nop)
    asm.emit(r_type(v0, z, ra, 0, 0x09))                 # jalr v0
    asm.emit(nop)
    asm.emit(i_type(0x23, sp, a2, 0))                    # callback may clobber args
    asm.emit(i_type(0x23, sp, a3, 4))
    asm.branch(0x04, v0, z, "failure")                  # Triangle/back cancels
    asm.emit(nop)
    asm.branch(0x04, z, z, "wait_loop")                 # callback clobbers t0-t2
    asm.emit(nop)

    # El frontend ya escribió la respuesta directamente en a2.
    asm.label("response_ready")
    asm.emit(i_type(0x23, t0, t2, 24))                    # recvSize
    asm.emit(nop)                                         # load delay
    asm.emit(r_type(a3, t2, t1, 0, 0x2B))                # sltu t1,a3,recvSize
    asm.branch(0x05, t1, z, "failure")
    asm.emit(nop)
    asm.emit(i_type(0x29, t0, z, 6))                     # status=IDLE
    asm.emit(i_type(0x09, z, v0, 1))
    asm.emit(i_type(0x23, sp, ra, 12))
    asm.emit(i_type(0x09, sp, sp, 16))
    asm.emit(r_type(ra, z, z, 0, 0x08))                  # jr ra
    asm.emit(nop)

    asm.label("failure")
    # Reconstruye siempre el puntero porque la validación puede saltar aquí
    # antes de inicializar t0 con la dirección del mailbox.
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(r_type(z, z, v0, 0, 0x21))                  # v0=0
    asm.emit(i_type(0x23, sp, ra, 12))
    asm.emit(i_type(0x09, sp, sp, 16))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(nop)

    code = asm.resolve()
    if FUNCTION_START + len(code) > MAILBOX_ADDRESS:
        raise ValueError("el stub invade el mailbox")
    return code


def build_gameplay_batch_transfer() -> bytes:
    """Agrupa las cuatro transferencias sincronas del tick de gameplay."""
    z, v0 = REG["zero"], REG["v0"]
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = (
        REG[name] for name in ("t0", "t1", "t2", "t3", "t4", "t5",
                              "t6", "t7", "t8", "t9")
    )
    s0, s4, s6, sp, ra = (REG[name] for name in ("s0", "s4", "s6", "sp", "ra"))
    asm = Assembler(GAMEPLAY_BATCH_FUNCTION)
    nop = 0

    # El juego conserva el numero local en -0x8C(s0) y el remoto en 4(s4).
    # Cada registro de vehiculo ocupa 0x18 bytes.
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x23, s0, t1, -0x8C))
    asm.emit(nop)                                         # load delay R3000A
    asm.emit(i_type(0x0B, t1, t9, 5))                   # 0..4 jugadores
    asm.branch(0x04, t9, z, "failure")
    asm.emit(nop)
    asm.emit(r_type(z, t1, t2, 4, 0x00))                # local * 16
    asm.emit(r_type(z, t1, t9, 3, 0x00))                # local * 8
    asm.emit(r_type(t2, t9, t2, 0, 0x21))               # localBytes
    asm.emit(i_type(0x23, s4, t3, 4))
    asm.emit(nop)                                         # load delay R3000A
    asm.emit(i_type(0x0B, t3, t9, 5))
    asm.branch(0x04, t9, z, "failure")
    asm.emit(nop)
    asm.emit(r_type(z, t3, t9, 4, 0x00))                # remote * 16
    asm.emit(r_type(z, t3, t3, 3, 0x00))                # remote * 8
    asm.emit(r_type(t3, t9, t3, 0, 0x21))               # remoteBytes
    asm.emit(i_type(0x09, t2, t4, 12))                  # sendTotal
    asm.emit(i_type(0x09, t3, t5, 12))                  # recvTotal

    # Cabecera TM3O v5: el frontend concatena/dispersa estos rangos de RAM.
    asm.emit(i_type(0x0F, z, t7, MAILBOX_MAGIC >> 16))
    asm.emit(i_type(0x0D, t7, t7, MAILBOX_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, t0, t7, 0))
    asm.emit(i_type(0x09, z, t7, MAILBOX_VERSION))
    asm.emit(i_type(0x29, t0, t7, 4))
    asm.emit(i_type(0x09, z, t7, MAILBOX_COMMAND_BATCH_TRANSFER))
    asm.emit(i_type(0x29, t0, t7, 8))
    asm.emit(i_type(0x2B, t0, z, 12))
    asm.emit(i_type(0x2B, t0, t4, 16))
    asm.emit(i_type(0x2B, t0, t5, 20))
    asm.emit(i_type(0x2B, t0, z, 24))
    asm.emit(i_type(0x2B, t0, ra, 28))
    asm.emit(i_type(0x2B, t0, z, 32))
    asm.emit(i_type(0x2B, t0, z, 36))
    asm.emit(i_type(0x09, z, t7, 4))
    asm.emit(i_type(0x2B, t0, t7, 40))
    asm.emit(i_type(0x2B, t0, t7, 44))

    # send = s0[4] + vehiculos locales[N*24] + dos palabras de estado.
    asm.emit(i_type(0x2B, t0, s0, 48))
    asm.emit(i_type(0x2B, t0, t7, 52))
    asm.emit(i_type(0x2B, t0, s6, 56))
    asm.emit(i_type(0x2B, t0, t2, 60))
    asm.emit(i_type(0x09, sp, t6, 0xAC))
    asm.emit(i_type(0x2B, t0, t6, 64))
    asm.emit(i_type(0x2B, t0, t7, 68))
    asm.emit(i_type(0x09, sp, t6, 0xB4))
    asm.emit(i_type(0x2B, t0, t6, 72))
    asm.emit(i_type(0x2B, t0, t7, 76))

    # recv = palabra temporal + vehiculos remotos[N*24] + dos palabras.
    asm.emit(i_type(0x09, sp, t6, 0xA8))
    asm.emit(i_type(0x2B, t0, t6, 80))
    asm.emit(i_type(0x2B, t0, t7, 84))
    asm.emit(r_type(s6, t2, t6, 0, 0x21))
    asm.emit(i_type(0x2B, t0, t6, 88))
    asm.emit(i_type(0x2B, t0, t3, 92))
    asm.emit(i_type(0x09, sp, t6, 0xB0))
    asm.emit(i_type(0x2B, t0, t6, 96))
    asm.emit(i_type(0x2B, t0, t7, 100))
    asm.emit(i_type(0x09, sp, t6, 0xB8))
    asm.emit(i_type(0x2B, t0, t6, 104))
    asm.emit(i_type(0x2B, t0, t7, 108))

    # Publicar status al final evita que el frontend lea una cabecera parcial.
    asm.emit(i_type(0x09, z, t7, 1))
    asm.emit(i_type(0x29, t0, t7, 6))
    asm.emit(i_type(0x09, z, t7, 3))
    asm.emit(i_type(0x09, z, t9, 4))
    asm.label("wait_loop")
    asm.emit(i_type(0x25, t0, t8, 6))
    asm.emit(nop)                                         # load delay R3000A
    asm.branch(0x04, t8, t7, "response_ready")
    asm.emit(nop)
    asm.branch(0x04, t8, t9, "failure")
    asm.emit(nop)
    asm.branch(0x04, z, z, "wait_loop")
    asm.emit(nop)

    asm.label("response_ready")
    asm.emit(i_type(0x23, t0, t8, 24))
    asm.emit(nop)                                         # load delay R3000A
    asm.branch(0x05, t8, t5, "failure")                 # lote exacto
    asm.emit(nop)
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(i_type(0x09, z, v0, 1))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(nop)

    asm.label("failure")
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(r_type(z, z, v0, 0, 0x21))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(nop)

    code = asm.resolve()
    if GAMEPLAY_BATCH_FUNCTION + len(code) > GAMEPLAY_BATCH_FUNCTION_END:
        raise ValueError("la rutina batch de gameplay no cabe")
    return code


def build_gameplay_batch_patch() -> bytes:
    """Sustituye cuatro jal LinkTransfer por una operacion batch."""
    size = GAMEPLAY_BATCH_PATCH_END - GAMEPLAY_BATCH_PATCH_START
    patch = bytearray(size)
    patch[:4] = struct.pack("<I", j_type(0x03, GAMEPLAY_BATCH_FUNCTION))
    return bytes(patch)


def build_expanded_ram_probe() -> bytes:
    """Activa 2 bancos de 8 MiB y exige RAM alta real, sin espejos."""
    z, v0 = REG["zero"], REG["v0"]
    t0, t1, t2, ra = (REG[name] for name in ("t0", "t1", "t2", "ra"))
    asm = Assembler(EXPANDED_RAM_PROBE)
    nop = 0

    # DRAM_CTRL: conserva timings y selecciona dos bancos de 8 MiB.
    asm.emit(i_type(0x0F, z, t0, DRAM_CONTROL_ADDRESS >> 16))
    asm.emit(i_type(0x23, t0, t1, DRAM_CONTROL_ADDRESS & 0xFFFF))
    asm.emit(nop)
    asm.emit(i_type(0x0D, t1, t1, 0x0E00))
    asm.emit(i_type(0x2B, t0, t1, DRAM_CONTROL_ADDRESS & 0xFFFF))

    # Una PS1 de 2 MiB espeja o ignora esta direccion. El core TM3O-16
    # proporciona memoria independiente hasta 0x80FFFFFF.
    asm.emit(i_type(0x0F, z, t0, EXPANDED_RAM_TEST_ADDRESS >> 16))
    asm.emit(i_type(0x0F, z, t1, MAILBOX_MAGIC >> 16))
    asm.emit(i_type(0x0D, t1, t1, MAILBOX_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, t0, t1, 0))
    asm.emit(i_type(0x23, t0, v0, 0))
    asm.emit(nop)
    asm.emit(r_type(v0, t1, v0, 0, 0x26))                # xor: cero si coincide
    asm.emit(i_type(0x0B, v0, v0, 1))                   # v0=1 si RAM alta funciona
    asm.emit(i_type(0x2B, t0, z, 0))

    # El frontend confirma por separado que RETRO_MEMORY_SYSTEM_RAM expone
    # 16 MiB. Ambas comprobaciones deben coincidir.
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x25, t0, t1, 10))
    asm.emit(nop)
    asm.emit(i_type(0x0C, t1, t1, 0x0300))               # conectado + RAM ampliada
    asm.emit(i_type(0x09, z, t2, 0x0300))
    asm.emit(r_type(t1, t2, t1, 0, 0x26))
    asm.emit(i_type(0x0B, t1, t1, 1))
    asm.emit(r_type(v0, t1, v0, 0, 0x24))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(nop)

    code = asm.resolve()
    if EXPANDED_RAM_PROBE + len(code) > EXPANDED_RAM_PROBE_END:
        raise ValueError("el probe de RAM ampliada no cabe")
    return code


def build_ready_probe() -> bytes:
    """Salta al detector de sesion y RAM ampliada de 16 MiB."""
    z = REG["zero"]
    asm = Assembler(READY_PROBE_START)
    asm.emit(j_type(0x02, EXPANDED_RAM_PROBE))             # tail call; conserva ra
    asm.emit(0)
    code = asm.resolve()
    if len(code) > READY_PROBE_END - READY_PROBE_START:
        raise ValueError("el probe de red no cabe")
    return code.ljust(READY_PROBE_END - READY_PROBE_START, b"\0")


def build_role_select() -> bytes:
    """Espera el rol bombeando el callback original que dibuja WAITING."""
    z, v0, s0, s1 = REG["zero"], REG["v0"], 16, 17
    t0, t1, t2 = REG["t0"], REG["t1"], REG["t2"]
    asm = Assembler(ROLE_SELECT_START)
    asm.label("start")
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.label("poll")
    asm.emit(i_type(0x25, t0, t1, 6))                     # status actual
    asm.emit(i_type(0x09, z, t2, 3))
    asm.branch(0x04, t1, t2, "response_ready")            # respuesta del frontend
    asm.emit(0)
    asm.emit(i_type(0x09, z, t2, 4))
    asm.branch(0x04, t1, t2, "failure")                   # limpia y vuelve a publicar
    asm.emit(0)
    asm.branch(0x05, t1, z, "pump_waiting")               # REQUEST/PROCESSING
    asm.emit(0)

    # 0x80051970 borra su callback en el delay slot del jal. No se puede
    # devolver 0 y esperar otro frame: hacerlo deja la pantalla negra.
    asm.emit(i_type(0x0F, z, t1, MAILBOX_MAGIC >> 16))
    asm.emit(i_type(0x0D, t1, t1, MAILBOX_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, t0, t1, 0))                     # magic
    asm.emit(i_type(0x09, z, t1, MAILBOX_VERSION))
    asm.emit(i_type(0x29, t0, t1, 4))                     # version
    asm.emit(i_type(0x09, z, t1, MAILBOX_COMMAND_ROLE))
    asm.emit(i_type(0x29, t0, t1, 8))                     # command=ROLE
    asm.emit(i_type(0x09, z, t1, 1))
    asm.emit(i_type(0x29, t0, t1, 6))                     # status=REQUEST

    # Reproduce los bucles originales de 0x80047D84/0x80047E30. El callback
    # de la tabla 0x800D3280 bombea gráficos/entrada y mantiene WAITING visible.
    asm.label("pump_waiting")
    asm.emit(i_type(0x23, s1, v0, 8))                     # lw v0,8(s1)
    asm.emit(0)
    asm.emit(r_type(v0, z, REG["ra"], 0, 0x09))          # jalr v0
    asm.emit(0)
    asm.emit(r_type(v0, z, s0, 0, 0x21))                 # move s0,v0
    asm.branch(0x04, s0, z, "abort")                     # cancelación/salida original
    asm.emit(0)
    asm.emit(j_type(0x02, asm.labels["start"]))            # callback puede destruir t0-t2
    asm.emit(0)

    asm.label("response_ready")
    asm.emit(i_type(0x25, t0, s0, 10))                    # flags: conectado|rol
    # El R3000A no hace visible el resultado de lhu hasta una instruccion
    # despues. Sin este nop, andi conserva el s0=1 devuelto por el callback y
    # ambas consolas terminan como rol 1 aunque el frontend asigne 1/2.
    asm.emit(0)
    asm.emit(i_type(0x0C, s0, s0, 0x00FF))                # solo rol 1/2
    asm.emit(i_type(0x29, t0, z, 6))                      # status=IDLE
    asm.branch(0x05, s0, z, "role_ready")
    asm.emit(0)
    asm.emit(j_type(0x02, asm.labels["pump_waiting"]))
    asm.emit(0)
    asm.label("failure")
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(j_type(0x02, asm.labels["start"]))
    asm.emit(0)
    asm.label("role_ready")
    asm.emit(j_type(0x02, ROLE_SELECT_END))               # salta todo el SIO previo
    asm.emit(0)
    asm.label("abort")
    asm.emit(j_type(0x02, 0x80048064))                    # epílogo original
    asm.emit(r_type(z, z, v0, 0, 0x21))                  # delay slot: v0=0
    code = asm.resolve()
    if len(code) > ROLE_SELECT_END - ROLE_SELECT_START:
        raise ValueError("la seleccion de rol no cabe")
    return code.ljust(ROLE_SELECT_END - ROLE_SELECT_START, b"\0")


def va_to_offset(address: int) -> int:
    return 0x800 + address - TEXT_ADDRESS


def create_ips(source: bytes, patched: bytes) -> bytes:
    records: list[tuple[int, bytes]] = []
    if source[MENU_OFFSET:MENU_OFFSET + len(NEW_MENU)] != patched[MENU_OFFSET:MENU_OFFSET + len(NEW_MENU)]:
        records.append((MENU_OFFSET, patched[MENU_OFFSET:MENU_OFFSET + len(NEW_MENU)]))
    regions = [
        (READY_PROBE_START, READY_PROBE_END - READY_PROBE_START),
        (FUNCTION_START, FUNCTION_END - FUNCTION_START),
        (ROLE_SELECT_START, ROLE_SELECT_END - ROLE_SELECT_START),
        (TAIL_BRANCH_ADDRESS, 4),
        (GAMEPLAY_BATCH_PATCH_START, GAMEPLAY_BATCH_PATCH_END - GAMEPLAY_BATCH_PATCH_START),
    ]
    for address, size in regions:
        offset = va_to_offset(address)
        if source[offset:offset + size] != patched[offset:offset + size]:
            records.append((offset, patched[offset:offset + size]))
    output = bytearray(b"PATCH")
    for offset, payload in records:
        output.extend(offset.to_bytes(3, "big"))
        output.extend(len(payload).to_bytes(2, "big"))
        output.extend(payload)
    output.extend(b"EOF")
    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reemplaza LinkTransfer/SIO de TM3 por el mailbox TM3O v5")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ips", type=Path, help="también escribe un parche IPS reproducible")
    args = parser.parse_args()

    source = args.source.read_bytes()
    if source[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: el archivo no es un PS-X EXE")
    before = hashlib.sha256(source).hexdigest()
    stub = build_stub()
    gameplay_batch = build_gameplay_batch_transfer()
    gameplay_patch = build_gameplay_batch_patch()
    expanded_ram_probe = build_expanded_ram_probe()
    ready_probe = build_ready_probe()
    role_select = build_role_select()
    function_offset = va_to_offset(FUNCTION_START)
    function_size = FUNCTION_END - FUNCTION_START
    mailbox_offset = va_to_offset(MAILBOX_ADDRESS)
    mailbox_end = MAILBOX_ADDRESS + MAILBOX_HEADER_SIZE
    if mailbox_end > GAMEPLAY_BATCH_FUNCTION:
        raise SystemExit("ERROR interno: el mailbox no cabe en la función reemplazada")

    already_patched = (
        source[function_offset:function_offset + len(stub)] == stub
        and source[mailbox_offset:mailbox_offset + 6] == struct.pack("<IH", MAILBOX_MAGIC, MAILBOX_VERSION)
        and source[va_to_offset(READY_PROBE_START):va_to_offset(READY_PROBE_END)] == ready_probe
        and source[va_to_offset(ROLE_SELECT_START):va_to_offset(ROLE_SELECT_END)] == role_select
        and source[va_to_offset(GAMEPLAY_BATCH_FUNCTION):
                   va_to_offset(GAMEPLAY_BATCH_FUNCTION) + len(gameplay_batch)] == gameplay_batch
        and source[va_to_offset(EXPANDED_RAM_PROBE):
                   va_to_offset(EXPANDED_RAM_PROBE) + len(expanded_ram_probe)] == expanded_ram_probe
        and source[va_to_offset(GAMEPLAY_BATCH_PATCH_START):
                   va_to_offset(GAMEPLAY_BATCH_PATCH_END)] == gameplay_patch
        and source[va_to_offset(TAIL_BRANCH_ADDRESS):va_to_offset(TAIL_BRANCH_ADDRESS) + 4]
        == struct.pack("<I", branch_word(0x04, REG["zero"], REG["zero"], TAIL_BRANCH_ADDRESS, TAIL_SUCCESS_ADDRESS))
    )
    if before not in {ORIGINAL_SHA256, MENU_SHA256, LEGACY_NETWORK_SHA256,
                      FIXED_ROLE_NETWORK_SHA256, BLOCKING_ROLE_NETWORK_SHA256,
                      RETURNING_ROLE_NETWORK_SHA256, PUMPED_ROLE_NETWORK_SHA256,
                      PAYLOAD_LOAD_DELAY_FIXED_NETWORK_SHA256,
                      ROLE_LOAD_DELAY_FIXED_NETWORK_SHA256} and not already_patched:
        raise SystemExit(f"ERROR: revisión desconocida, SHA-256={before}")

    patched = bytearray(source)
    if patched[MENU_OFFSET:MENU_OFFSET + len(OLD_MENU)] == OLD_MENU:
        patched[MENU_OFFSET:MENU_OFFSET + len(NEW_MENU)] = NEW_MENU
    elif patched[MENU_OFFSET:MENU_OFFSET + len(NEW_MENU)] != NEW_MENU:
        raise SystemExit("ERROR: el texto de menú esperado no está en su offset conocido")

    patched[function_offset:function_offset + function_size] = bytes(function_size)
    patched[function_offset:function_offset + len(stub)] = stub
    patched[va_to_offset(GAMEPLAY_BATCH_FUNCTION):
            va_to_offset(GAMEPLAY_BATCH_FUNCTION) + len(gameplay_batch)] = gameplay_batch
    patched[va_to_offset(EXPANDED_RAM_PROBE):
            va_to_offset(EXPANDED_RAM_PROBE) + len(expanded_ram_probe)] = expanded_ram_probe
    header = bytearray(MAILBOX_HEADER_SIZE)
    struct.pack_into("<IHHHH", header, 0, MAILBOX_MAGIC, MAILBOX_VERSION, 0,
                     MAILBOX_COMMAND_TRANSFER, 0)
    assert len(header) == MAILBOX_HEADER_SIZE
    patched[mailbox_offset:mailbox_offset + len(header)] = header
    patched[va_to_offset(READY_PROBE_START):va_to_offset(READY_PROBE_END)] = ready_probe
    patched[va_to_offset(ROLE_SELECT_START):va_to_offset(ROLE_SELECT_END)] = role_select
    patched[va_to_offset(TAIL_BRANCH_ADDRESS):va_to_offset(TAIL_BRANCH_ADDRESS) + 4] = struct.pack(
        "<I", branch_word(0x04, REG["zero"], REG["zero"], TAIL_BRANCH_ADDRESS, TAIL_SUCCESS_ADDRESS)
    )
    patched[va_to_offset(GAMEPLAY_BATCH_PATCH_START):
            va_to_offset(GAMEPLAY_BATCH_PATCH_END)] = gameplay_patch

    args.output.write_bytes(patched)
    if args.ips:
        args.ips.write_bytes(create_ips(source,patched))
    after = hashlib.sha256(patched).hexdigest()
    print(f"OK: {args.output}")
    print(f"Stub: 0x{FUNCTION_START:08X}-0x{FUNCTION_START + len(stub):08X} ({len(stub)} bytes)")
    print(f"Batch: 0x{GAMEPLAY_BATCH_FUNCTION:08X}-0x{GAMEPLAY_BATCH_FUNCTION + len(gameplay_batch):08X} "
          f"({len(gameplay_batch)} bytes)")
    print(f"RAM probe: 0x{EXPANDED_RAM_PROBE:08X}-0x{EXPANDED_RAM_PROBE + len(expanded_ram_probe):08X}; "
          "requiere 16 MiB reales")
    print(f"Mailbox: 0x{MAILBOX_ADDRESS:08X}-0x{mailbox_end:08X} "
          f"(punteros directos, max {MAX_TRANSFER} bytes)")
    print("Gameplay: cuatro esperas SIO agrupadas en una transferencia UDP por tick")
    print("Roles dinamicos: primera consola en espera=1; segunda consola=2/autoridad")
    print("Espera inicial: bucle original bombeado; WAITING visible hasta que entre la segunda consola")
    print(f"SHA-256 entrada: {before}")
    print(f"SHA-256 salida:  {after}")
    if args.ips:
        print(f"IPS: {args.ips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
