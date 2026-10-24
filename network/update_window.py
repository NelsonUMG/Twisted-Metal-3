"""Main-thread update dialog; workers communicate only through the lobby queue."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from privacy import public_text

class UpdateWindow:
    def __init__(self, owner, update):
        self.owner, self.update = owner, update
        self.cancelled = threading.Event()
        self.path = None
        self.window = tk.Toplevel(owner.root)
        self.window.title('Actualizar TM3 Online')
        self.window.geometry('480x230'); self.window.resizable(False, False)
        self.window.transient(owner.root)
        frame = ttk.Frame(self.window, padding=18); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f"Nueva versión {update['version']}", style='Title.TLabel').pack(anchor='w')
        self.status = ttk.Label(frame, text='Conectando para comparar los archivos de la actualización…'); self.status.pack(anchor='w', pady=(14,6))
        self.bar = ttk.Progressbar(frame, maximum=update.get('size',100)); self.bar.pack(fill='x')
        ttk.Label(frame, text='Se verifica SHA256 antes de instalar. Tus ajustes y partidas se conservan.', wraplength=440).pack(anchor='w', pady=10)
        self.file_log = tk.Text(frame, height=4, width=54, state='disabled', font=('Segoe UI',9))
        self.file_log.pack(fill='both', expand=True, pady=(0,8))
        self.window.geometry('500x320')
        self.restart = ttk.Button(frame, text='Reiniciar', command=self.apply, state='disabled'); self.restart.pack(side='right')
        self.later = ttk.Button(frame, text='Cancelar', command=self.hide); self.later.pack(side='right', padx=8)
        self.window.protocol('WM_DELETE_WINDOW', self.hide)
        def download():
            from release_updater import download_installer
            try:
                if update.get('mode') == 'files':
                    from file_updater import download_files
                    path=download_files(update, owner.install_root, owner.update_cache,
                        lambda done,total,name: owner.events.put(('release_progress',(done,total,name))), self.cancelled)
                else: path = download_installer(update, owner.update_cache,
                    lambda done,total: owner.events.put(('release_progress', (done,total))), self.cancelled)
                owner.events.put(('release_downloaded', path if isinstance(path,dict) else str(path)))
            except Exception as exc: owner.events.put(('release_failed', str(exc)))
        threading.Thread(target=download, daemon=True).start()

    def hide(self):
        self.cancelled.set()
        self.window.destroy()

    def progress(self, done, total, name=None):
        if not self.window.winfo_exists(): return
        self.bar['maximum'] = max(1,total)
        self.bar['value'] = done
        if name and name != getattr(self,'last_file',None):
            self.last_file=name
            self.file_log.configure(state='normal');self.file_log.insert('end',name+'\n');self.file_log.see('end');self.file_log.configure(state='disabled')
        self.status.configure(text=f'Descargando archivos: {done/1048576:.1f} / {total/1048576:.1f} MiB')

    def ready(self, path):
        if not self.window.winfo_exists(): return
        self.path = path; self.bar['value'] = self.bar['maximum']
        self.status.configure(text='Descarga verificada. Pulsa Reiniciar para aplicar los cambios.')
        self.restart.configure(state='normal'); self.window.deiconify()

    def failed(self, error):
        if not self.window.winfo_exists(): return
        self.status.configure(text='No se pudo descargar: ' + public_text(error), wraplength=440)
        self.later.configure(text='Cerrar', command=self.window.destroy)
        self.window.deiconify()

    def apply(self):
        owner = self.owner
        if owner.room or any(p and p.poll() is None for p in (owner.process, owner.local_process)):
            if not messagebox.askyesno('Reiniciar', 'Se cerrará la sala y la partida de este equipo para actualizar. ¿Continuar?', parent=self.window): return
        from release_updater import launch_installer
        try:
            if self.update.get('mode') == 'files':
                from file_updater import launch_apply
                launch_apply(self.path)
            else: launch_installer(self.path, owner.install_root, self.update)
        except Exception as exc:
            self.failed(str(exc)); return
        self.restart.configure(state='disabled')
        owner.close()
