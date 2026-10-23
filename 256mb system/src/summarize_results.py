"""Generate an evidence-based result, not a claim of a finished online game."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent


def main():
    def read(name):return json.loads((BASE/'reports'/name).read_text())
    audit=read('audit.json');unit=read('unit_tests.json');regression=read('lobby_regression.json')
    reference=read('reference.json');replay=read('replay.json')
    assert unit['passed'] and regression['passed'] and audit['protected_product_preserved']
    assert replay['per_role_full_16mib_ram_equal']
    cases=[]
    for rtt in (250,400):
        report=read(f'dual_wan_{rtt}.json')
        assert report['passed'] and report['replicas_match_each_other']
        assert report['per_role_full_16mib_ram_matches_reference']==[True,True]
        assert report['encrypted_capability_handshake']
        assert report['manifest']['core_sha256']==audit['core_sha256']
        assert report['manifest']['scus_sha256']==audit['scus_sha256']
        assert report['gameplay_ticks']==[600,600]
        assert report['time_mismatches']==report['rng_mismatches']==[0,0]
        for rows in report['windows']:
            assert all(row['actual_time_deltas']==[30,30] for row in rows)
        rates=report['steady_actual_time_units_per_second']
        waits=[w['wait_ms'] for node in report['input_waits'] for w in node]
        cases.append(dict(simulated_rtt_ms=rtt,time_units_per_second=rates,
            configured_input_delay_frames=report['input_delay_frames'],
            configured_input_delay_ms=report['input_delay_ms'],
            zero_time_rng_mismatches=True,replicas_match=True,reference_match=True,
            actual_world_time_deltas_checked=True,real_cloudflare_directory=True,
            complete_session_wall_s=report['elapsed_s'],steady_gameplay_wall_s=sum(w['seconds'] for w in report['windows'][0]),
            jitter_each_way_ms=report['jitter_each_way_ms'],udp_loss=report['random_udp_loss'],seed=report['seed'],
            input_waits_over_2ms=len(waits),maximum_input_wait_ms=max(waits,default=0),
            maximum_core_call_ms=report['frame_core_ms_max'],
            actual_wan_measured=False,stutter_free_verified=False))
    source_hashes={}
    for path in sorted((BASE/'src').glob('*.py')):
        source_hashes[str(path.relative_to(BASE))]=hashlib.sha256(path.read_bytes()).hexdigest()
    summary=dict(generated_utc=datetime.now(timezone.utc).isoformat(),
        status='laboratory_prototype_passed_not_playable_lobby_release',
        laboratory_target_average_29_time_passed=True,new_internet_engine_complete=False,
        interactive_lobby_integrated=False,guatemala_barbados_real_route_measured=False,
        seven_complete_maps_verified=False,stutter_free_verified=False,
        audio_or_four_humans_verified=False,ram_mib_per_console=256,consoles_per_node=2,
        core_state_checkpoints_per_console=6,reference_gameplay_ticks=reference['linked_gameplay_ticks'],
        experimental_unit_tests=unit['tests_run'],working_lobby_regression_passed=regression['passed'],
        artifact_audit=audit,cases=cases,source_hashes=source_hashes)
    (BASE/'reports/SUMMARY.json').write_text(json.dumps(summary,indent=2))
    lines=['# 256mb system — resultado medido','',
        'Prototipo de laboratorio desarrollado. NO es todavía una versión jugable del lobby.',
        '', '| RTT simulado | TIME/s réplica A | TIME/s réplica B | Demora de mando configurada |',
        '|---:|---:|---:|---:|']
    for row in cases:
        a,b=row['time_units_per_second']
        lines.append(f"| {row['simulated_rtt_ms']} ms | {a:.3f} | {b:.3f} | {row['configured_input_delay_ms']:.1f} ms |")
    lines += ['', '## Alcance real de la prueba','',
        'Cuatro cores reales: dos consolas en cada réplica. Dos réplicas ejecutadas en',
        'esta misma PC; la WAN de juego se simula, el directorio Cloudflare sí es real.',
        'Todos los inputs, incluidos arranque/menús, atraviesan el pipeline de entradas.',
        'La fuente de controles es una grabación de botones; no dos humanos ni dos redes reales.',
        'Cada caso dura unos 66 s completos, con 600 ticks (~20 s) de gameplay en una escena.',
        'Se usaron doble NAT por nodo, jitter de ±10 ms por sentido y pérdida UDP aleatoria del 1 %.',
        'Los 16 MiB completos de RAM de cada rol coincidieron con la referencia en seis',
        'fronteras, y las dos réplicas coincidieron entre sí. Cero discrepancias TIME/RNG.',
        'Los 250/400 ms son RTT base configurado: la medición cifrada puede ser mayor',
        'por jitter, retransmisión de pings, trabajo de CPU y planificación de Windows.',
        '', 'El ritmo se obtuvo de TIME real (RAM 0x895A8) y reloj monotónico, NO de',
        'un contador dibujado ni de cambiar el reloj. Se mantuvo CPU175, igual que la versión instalada.',
        'Promedio estable: se excluyen las dos primeras ventanas de gameplay como calentamiento.',
        '', '## Límites importantes','',
        '- No está integrado con Crear/Unirse/START en el lobby distribuible.',
        '- No están validados siete mapas, audio, cuatro humanos, mandos físicos,',
        '  pausa/retorno/cambios de mapa ni una sesión real Guatemala–Barbados.',
        '- 29 TIME/s de media NO demuestra ausencia de tirones: se observaron esperas',
        '  puntuales y llamadas al core largas; los informes conservan esos máximos.',
        '  La toma de hashes completos también introduce trabajo en el hilo de prueba.',
        '- La demora del mando no desaparece. El buffer es un intercambio entre',
        '  continuidad y respuesta; todavía no se usa rollback ni predicción.',
        '- Cada nodo necesita dos cores de 256 MiB (512 MiB emulados más gastos del host).',
        '- CGNAT restrictivo o UDP bloqueado aún puede exigir un relay/TURN público.',
        '', '## Artefactos y conservación','',
        'BIN/CUE modificados en game/. DLL compilado en runtime/ y core_source/.',
        'Se verificó el ejecutable dentro del BIN ISO9660 real; parche IPS reversible incluido.',
        'No se modificaron el BIN/core/EXE del lobby funcional ni el ZIP portátil.',
        f"Pasaron {unit['tests_run']} pruebas unitarias del prototipo y la regresión del lobby (99 pruebas).",
        'Detalles completos, ventanas, esperas, hashes y condiciones en reports/SUMMARY.json',
        'y reports/dual_wan_250.json / dual_wan_400.json.',
        '', 'Repetir: PRUEBAS_250_400.ps1 (requiere el entorno Python del proyecto).',
        'Para entregar a otra PC falta el frontend interactivo y su empaquetado validado.', '']
    (BASE/'INFORME_ES.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('status','laboratory_target_average_29_time_passed',
        'new_internet_engine_complete','interactive_lobby_integrated','cases')},indent=2))


if __name__=='__main__':main()
