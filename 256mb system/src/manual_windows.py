"""Manual display/input only; simulation and network stay in the tested adapter."""
import json
from pathlib import Path
import struct
import time
import tkinter as tk


class ManualWindows:
    def __init__(self,base,rtt):
        self.rtt=rtt
        self.root=tk.Tk();self.root.title('NUEVO MOTOR 256 · control de prueba')
        self.root.geometry('670x160+10+10');self.closed=False
        self.keys=[set(),set()];self.windows=[];self.labels=[];self.photos=[None,None];self.previous=[None,None]
        self.report=Path(base)/f'reports/manual_new_{rtt}.json';self.last_report=0;self.last_times=None
        tk.Label(self.root,text=f'NUEVO MOTOR · {rtt} ms RTT base simulado',font=('Segoe UI',15,'bold')).pack(pady=8)
        self.status=tk.Label(self.root,text='Arrancando cuatro cores: dos réplicas con cámara propia.');self.status.pack()
        tk.Label(self.root,text='Haz clic en cada consola para controlarla. Prototipo manual SIN AUDIO.').pack()
        tk.Button(self.root,text='Cerrar las dos consolas nuevas',command=self.close).pack(pady=8)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        for node in (0,1):
            window=tk.Toplevel(self.root);window.title(f'CONSOLA {node+1} — NUEVO MOTOR 256 — {rtt} ms RTT')
            window.geometry(f'660x570+{20+node*680}+190')
            label=tk.Label(window,bg='black',text='Cargando TM3…',fg='white');label.pack(fill='both',expand=True)
            tk.Label(window,text='WASD: dirección · F: X/seleccionar · V: START · T: triángulo/atrás\nJ: círculo · C: cuadrado · H: L1 · G: L2 · Y: R2').pack()
            window.bind('<KeyPress>',lambda e,n=node:self.keys[n].add(e.keycode))
            window.bind('<KeyRelease>',lambda e,n=node:self.keys[n].discard(e.keycode))
            window.bind('<FocusOut>',lambda e,n=node:self.keys[n].clear())
            label.bind('<Button-1>',lambda e,w=window:w.focus_force())
            window.protocol('WM_DELETE_WINDOW',self.close)
            self.windows.append(window);self.labels.append(label)
        self.root.update()

    def sample(self,node,frame):
        bindings=[70,67,0,86,87,83,65,68,74,84,72,0,71,89,0,0]
        return sum(1<<i for i,key in enumerate(bindings) if key and key in self.keys[node])

    def close(self):
        self.closed=True

    def update(self,cores,cables,peers,feeds):
        self.root.update()
        if self.closed:return
        for node in (0,1):
            core=cores[node][node];video=core.video
            if video is None or video is self.previous[node]:continue
            self.previous[node]=video
            data,width,height,pitch,fmt=video
            packed=b''.join(data[y*pitch:y*pitch+width*(4 if fmt==1 else 2)] for y in range(height))
            rgb=bytearray(width*height*3)
            if fmt==1:
                rgb[0::3]=packed[2::4];rgb[1::3]=packed[1::4];rgb[2::3]=packed[0::4]
            else:
                for i,(v,) in enumerate(struct.iter_unpack('<H',packed)):
                    rgb[i*3]=((v>>(11 if fmt==2 else 10))&31)*255//31
                    rgb[i*3+1]=((v>>5)&(63 if fmt==2 else 31))*255//(63 if fmt==2 else 31)
                    rgb[i*3+2]=(v&31)*255//31
            photo=tk.PhotoImage(data=f'P6\n{width} {height}\n255\n'.encode()+rgb,format='PPM')
            if width<=330 and height<=250:photo=photo.zoom(2)
            self.photos[node]=photo;self.labels[node].configure(image=photo,text='')
        now=time.monotonic()
        if now-self.last_report>=1:
            times=[cores[n][n].word(0x895a8) for n in (0,1)]
            rates=[None,None]
            if self.last_times:
                dt=now-self.last_times[0]
                rates=[(a-b)/dt if 0<=a-b<100 else None for a,b in zip(times,self.last_times[1])]
            self.last_times=(now,times);self.last_report=now
            snapshots=[p.latency_snapshot() for p in peers]
            text=' | '.join(f'C{n+1}: ping {snapshots[n]["rtt_ms"] or 0:.0f} ms · TIME/s {rates[n] or 0:.1f}' for n in (0,1))
            text+=f' | Margen mando: {feeds[0].delay/59.94*1000:.0f} ms'
            failures=[c.error for c in cables if c.error]+[f.error for f in feeds if f.error]
            self.status.configure(text='ERROR: '+str(failures) if failures else text)
            self.report.write_text(json.dumps(dict(engine='NEW SYSTEM256 ABI6',helper_pid=__import__('os').getpid(),
                simulated_rtt_ms=self.rtt,one_way_ms=self.rtt/2,manual_inputs=True,audio_enabled=False,
                configured_input_delay_frames=feeds[0].delay,configured_input_delay_ms=feeds[0].delay/59.94*1000,
                peer_rtt=snapshots,time_values=times,time_per_second=rates,
                gameplay_ticks=[c.gameplay for c in cables],cable_errors=[c.error for c in cables],
                time_mismatches=[c.time_mismatches for c in cables],rng_mismatches=[c.rng_mismatches for c in cables],
                core_frames=[[c.frame for c in pair] for pair in cores]),indent=2))

    def destroy(self):
        self.root.destroy()
