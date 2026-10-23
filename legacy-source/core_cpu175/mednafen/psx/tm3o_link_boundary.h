/* Sparse host-clock brackets around guest publication and resume. No guest writes. */
#ifndef TM3O_LINK_BOUNDARY_H
#define TM3O_LINK_BOUNDARY_H
#include <windows.h>
static FILE *lb_file;
static int lb_init,lb_enabled,lb_store,lb_active;
static unsigned lb_rows;
static uint32_t lb_time,lb_pop,lb_map;
static uint64_t lb_before,lb_after,lb_ready,lb_hz;
static uint64_t lb_now(void){LARGE_INTEGER q;QueryPerformanceCounter(&q);return (uint64_t)q.QuadPart;}
static void lb_close(void){if(lb_file)fclose(lb_file);lb_file=NULL;lb_enabled=0;}
static void LB_Before(uint32_t pc,uint32_t instr,uint32_t opf,uint32_t v0){
 if(!lb_init){
  const char *path=getenv("TM3O_LINK_BOUNDARY_FILE");lb_init=1;
  if(path && *path)lb_file=fopen(path,"wbx");
  if(lb_file){LARGE_INTEGER f;QueryPerformanceFrequency(&f);lb_hz=f.QuadPart;lb_enabled=1;atexit(lb_close);
   fputs("tick,sequence,time_start,time_end,pop_start,pop_end,map_start,map_end,valid,v0,qpc_hz,publish_before,publish_after,ready_guest,resume_guest\n",lb_file);fflush(lb_file);}
 }
 if(!lb_enabled || (opf&0x80U))return;
 if(pc==0x80047AF0U && instr==0xA50F0006U){
  lb_active=pace_scene();lb_store=lb_active;lb_ready=0;
  lb_time=TM3O_OC_Read(0x800895A8U);lb_pop=TM3O_OC_Read(0x800D3234U);lb_map=TM3O_OC_Read(0x800D2CC4U);
  if(lb_active)lb_before=lb_now();
 }else if(lb_active && pc==0x80047B1CU && !lb_ready){lb_ready=lb_now();
 }else if(lb_active && pc==0x8003AA98U){
  uint64_t resume=lb_now();uint32_t end=TM3O_OC_Read(0x800895A8U),pop=TM3O_OC_Read(0x800D3234U),map=TM3O_OC_Read(0x800D2CC4U);
  int valid=pace_scene() && end==lb_time && pop==lb_pop && map==lb_map && v0==1 && lb_ready && lb_after>=lb_before;
  fprintf(lb_file,"%u,%u,%u,%u,%u,%u,%u,%u,%d,%u,%llu,%llu,%llu,%llu,%llu\n",
    ++lb_rows,TM3O_OC_Read(0x8004790CU),lb_time,end,lb_pop,pop,lb_map,map,valid,v0,
    (unsigned long long)lb_hz,(unsigned long long)lb_before,(unsigned long long)lb_after,
    (unsigned long long)lb_ready,(unsigned long long)resume);
  lb_active=0;if(fflush(lb_file)!=0 || lb_rows>=1200)lb_close();
 }
}
static void LB_After(void){if(lb_store){lb_after=lb_now();lb_store=0;}}
#endif
