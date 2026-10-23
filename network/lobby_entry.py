"""Frozen executable entry: GUI, detached directory, or offline runtime check."""
import json
import ctypes
from pathlib import Path
import sys
import time

_LOBBY_MUTEX = None


def acquire_lobby_mutex():
    global _LOBBY_MUTEX
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, True, 'Local\\TwistedMetal3OnlineLobby.Singleton.v1')
    if not handle:
        raise OSError('No se pudo proteger la instancia del lobby.')
    duplicate = kernel.GetLastError() == 183
    if duplicate:
        kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        _LOBBY_MUTEX = handle
    return not duplicate


def main():
    if '--system256' in sys.argv:
        sys.argv.remove('--system256')
        from system256_runtime import main as run_engine
        try:
            run_engine()
        except Exception as exc:
            # Runtime failures are reported to the lobby through the session
            # file. Do not turn a normal peer disconnect into a PyInstaller
            # unhandled-exception dialog. Also cover audio/video init failures
            # which can occur before the runtime's main try/finally block.
            import traceback
            try:
                state_path = Path(sys.argv[sys.argv.index('--state') + 1])
                current = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
                if current.get('state') != 'failed':
                    log_directory = (Path(sys.argv[sys.argv.index('--log-directory') + 1])
                                     if '--log-directory' in sys.argv else state_path.parent)
                    error_path = log_directory/'ERROR_TM3_ONLINE.txt'
                    error_path.write_text(traceback.format_exc(), encoding='utf-8-sig')
                    current.update(state='failed', error=str(exc), error_log=str(error_path))
                    state_path.write_text(json.dumps(current), encoding='utf-8')
            except Exception:
                pass
            return 1
        return 0
    if '--check-directory' in sys.argv:
        from rooms_probe import run_check
        index = sys.argv.index('--check-directory')
        target = Path(sys.argv[index + 2])
        try:
            result = run_check(sys.argv[index + 1])
        except Exception as exc:
            result = dict(passed=False, error=type(exc).__name__ + ': ' + str(exc))
        result['frozen'] = bool(getattr(sys, 'frozen', False))
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return 0 if result['passed'] else 1
    elif '--check-ice' in sys.argv:
        from p2p_probe import run_check
        target = Path(sys.argv[sys.argv.index('--check-ice') + 1])
        try:
            result = run_check()
        except Exception as exc:
            result = dict(passed=False, error=type(exc).__name__ + ': ' + str(exc))
        result['frozen'] = bool(getattr(sys, 'frozen', False))
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return 0 if result['passed'] else 1
    elif "--lobby-server" in sys.argv:
        sys.argv.remove("--lobby-server")
        from lobby_server import main as serve
        serve()
    elif "--relay-server" in sys.argv:
        sys.argv.remove("--relay-server")
        from relay_server import main as serve
        serve()
    elif "--check-shutdown" in sys.argv:
        import tkinter as tk
        from lobby_client import Lobby, DATA
        from lobby_server import LocalDirectory
        target = Path(sys.argv[sys.argv.index("--check-shutdown") + 1])
        root = tk.Tk()
        root.withdraw()
        gui = Lobby(root)
        for timer in root.tk.call("after", "info"):
            root.after_cancel(timer)
        gui.owned_directory = LocalDirectory(DATA / "shutdown_test.sqlite3", port=0)
        directory = gui.owned_directory
        game = None
        try:
            game = gui.launch_game("shutdown_qa", [])
            time.sleep(.8)
        except Exception as exc:
            report_error = type(exc).__name__ + ': ' + str(exc)
        else:
            report_error = None
        finally:
            gui.close()
        report.update(game_exited=game is not None and game.poll() is not None,
                      directory_threads_stopped=all(not t.is_alive() for t in directory.threads),
                      frozen=bool(getattr(sys, "frozen", False)), error=report_error)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if report["game_exited"] and report["directory_threads_stopped"] else 1
    elif "--check-runtime" in sys.argv:
        from lobby_client import Lobby, ROOT, load_config
        target = Path(sys.argv[sys.argv.index("--check-runtime") + 1])
        report = dict(root=str(ROOT), frozen=bool(getattr(sys, "frozen", False)))
        try:
            client = Lobby.__new__(Lobby)
            client.config = load_config()
            client.process = None
            exe, core, game = client.runtime()
            report.update(ok=True, executable=str(exe), core=str(core), game=str(game), variant=client.config.get("runtime", {}).get("variant"))
            import ssl
            from relay_client import RelayBridge
            from relay_protocol import VERSION
            from worker_directory import WorkerDirectory
            from p2p_session import P2PSession
            tls = ssl.create_default_context()
            report.update(relay_protocol=VERSION, relay_bridge_available=callable(RelayBridge),
                          automatic_rooms_available=callable(WorkerDirectory) and callable(Lobby.negotiate_room),
                          peer_latency_available=callable(P2PSession.latency_snapshot),
                          public_directory_configured=bool(client.config.get('directory_url')),
                          relay_tls_verified=tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED)
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            try:
                gui = Lobby(root)
                gui.show_room = lambda: None
                room = dict(id="qa-only", description="Sala de prueba", host="Prueba", players=["Prueba"], capacity=2,
                            owner=True, phase="waiting", error="", joinable=True, chat=[])
                gui.render({"room": room, "rooms": [room]})
                root.update_idletasks()
                report.update(gui_ok=True, chat_available=bool(gui.chat_input.winfo_exists()), room_window=bool(gui.room_window.winfo_exists()),
                              manual_p2p_ui_removed=not hasattr(gui, 'p2p_button') and not hasattr(gui, 'open_p2p'),
                              peer_latency_ui=bool(gui.latency_label.winfo_exists()) and bool(gui.room_latency.winfo_exists()),
                              columns=list(gui.table["columns"]), local_button=gui.local_button.cget("text"),
                              diagnostics_enabled=client.config.get("runtime", {}).get("diagnostics", False),
                              cpu_budget_percent=client.config.get("runtime", {}).get("environment", {}).get("TM3O_CPU_BUDGET_PERCENT"))
            finally:
                root.destroy()
        except Exception as exc:
            report.update(ok=False, error=str(exc))
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if report["ok"] else 1
    elif '--qa-lobby-lock' in sys.argv:
        index = sys.argv.index('--qa-lobby-lock')
        target, seconds = Path(sys.argv[index + 1]), float(sys.argv[index + 2])
        owned = acquire_lobby_mutex()
        target.write_text(json.dumps({'lock_acquired': owned}), encoding='utf-8')
        if owned: time.sleep(seconds)
        return 0 if owned else 3
    else:
        if not acquire_lobby_mutex():
            from lobby_client import ROOT
            language = ctypes.windll.kernel32.GetPrivateProfileIntW(
                'Console', 'Language', 0, str(ROOT/'runtime/TM3Console.ini'))
            text = ('You already have the Twisted Metal 3 lobby open.' if language == 0
                    else 'Ya tiene abierto el lobby de Twisted metal 3')
            ctypes.windll.user32.MessageBoxW(None, text, 'TM3 Online', 0x40)
            return 3
        from lobby_client import main as gui
        gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
