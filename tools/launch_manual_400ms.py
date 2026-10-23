"""Interactive ORIGINAL engine, two visible consoles, 400 ms base RTT.

No system network settings change. Never use the SYSTEM256 ABI6 BIN here.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import tkinter as tk

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT/'network'),str(ROOT/'tools')]
from ice_nat_lab import NatNetwork,SimulatedP2PSession,isolated_ice_addresses
from lobby_client import listening


def main():
    folder=ROOT/'diagnostics/manual_400ms'/str(time.time_ns())
    folder.mkdir(parents=True)
    report_path=ROOT/'diagnostics/manual_400ms/latest.json'
    peers=[];games=[]
    network=NatNetwork(latency_ms=200,jitter_ms=0,loss=0)
    root=tk.Tk();root.title('TM3 — prueba manual 400 ms RTT (motor original)')
    root.geometry('630x270')
    tk.Label(root,text='DOS CONSOLAS · 400 ms RTT SIMULADOS',font=('Segoe UI',16,'bold')).pack(pady=12)
    tk.Label(root,text='Motor ORIGINAL, no el nuevo 256mb system.\n200 ms por sentido · sin jitter ni pérdida añadidos.').pack()
    status=tk.Label(root,text='Preparando conexión…');status.pack(pady=12)
    tk.Label(root,text='En cada ventana: NEW GAME → MODO ONLINE? → YES.\nHaz clic en la ventana que quieras controlar. Usa tus teclas habituales.').pack()
    tk.Button(root,text='Cerrar prueba y ambas consolas',command=root.destroy).pack(pady=10)
    root.update()
    try:
        with isolated_ice_addresses():
            peers=[SimulatedP2PSession(network,side) for side in (0,1)]
            host,guest=peers
            host.accept_answer(guest.create_answer(host.create_offer()))
            assert host.connected.wait(20) and guest.connected.wait(20),'No se estableció ICE'
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            guest_port=guest.attach_game(generation=1)
            env={k:v for k,v in os.environ.items() if not k.startswith('TM3O_')}
            env.update(TM3O_DIAGNOSTICS='1',TM3O_LINK_HIRES_WAIT='1',TM3O_LINK_UDP_WAKE='1')
            for side,mode in ((0,['--host',str(port)]),(1,['--join',f'127.0.0.1:{guest_port}'])):
                target=folder/str(side);target.mkdir()
                exe=target/f'TM3_Prueba_{"A" if side==0 else "B"}.exe'
                shutil.copy2(ROOT/'TM3Online_Lobby/runtime/TM3Online.exe',exe)
                shutil.copy2(ROOT/'TM3Online_Lobby/runtime/TM3Console.ini',target/'TM3Console.ini')
                state=target/'session.json'
                games.append(subprocess.Popen([str(exe),'--windowed','--core',
                    str(ROOT/'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll'),
                    '--game',str(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue'),
                    '--parent-pid',str(os.getpid()),'--session-state',str(state),
                    '--save-slot',f'prueba_{side}',*mode],cwd=target,env=env))
                if side==0:
                    deadline=time.monotonic()+8
                    while not listening(games[0].pid,port):
                        if games[0].poll() is not None or time.monotonic()>deadline:raise RuntimeError('El anfitrión no abrió su puerto')
                        root.update();time.sleep(.05)
                    host.attach_game(port,generation=1)
            def update():
                views=[p.latency_snapshot() for p in peers]
                measured=['—' if v['rtt_ms'] is None else f"{v['rtt_ms']:.0f}" for v in views]
                status.configure(text=f'Ping medido A / B: {measured[0]} / {measured[1]} ms')
                report=dict(helper_pid=os.getpid(),game_pids=[p.pid for p in games],folder=str(folder),
                    engine='original installed engine, NOT system256',simulated_rtt_ms=400,
                    one_way_ms=200,jitter_ms=0,loss=0,peer_rtt=views,
                    game_exits=[p.poll() for p in games],network=network.snapshot())
                report_path.write_text(json.dumps(report,indent=2))
                if all(p.poll() is not None for p in games):root.destroy();return
                root.after(1000,update)
            update();root.mainloop()
    except Exception as exc:
        report_path.write_text(json.dumps(dict(error=repr(exc),folder=str(folder))))
        raise
    finally:
        for peer in peers:peer.close()
        # On this helper's exit, each native game's parent-PID watchdog closes
        # its own window gracefully. Never touch unrelated game processes.


if __name__=='__main__':main()
