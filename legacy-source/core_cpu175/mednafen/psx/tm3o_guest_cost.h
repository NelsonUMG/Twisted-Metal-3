/* Host-only counters; no guest memory/register/clock writes. Eligible
 * pre-dispatch visits, not retired instructions. Cycle span is whole interval. */
#ifndef TM3O_GUEST_COST_H
#define TM3O_GUEST_COST_H
#include "tm3o_cost_map.h"
static FILE *tm3o_cost_file;
static int tm3o_cost_init, tm3o_cost_enabled, tm3o_cost_active;
static uint64_t tm3o_cost_counts[TM3O_COST_FUNCTIONS];
static uint64_t tm3o_cost_total, tm3o_cost_irqs, tm3o_cost_cycles, tm3o_cost_start_cycles;
static uint64_t tm3o_cost_start_total, tm3o_cost_start_irqs, tm3o_cost_frames, tm3o_cost_start_frames;
static int32_t tm3o_cost_last_ts;
static uint32_t tm3o_cost_tick, tm3o_cost_start_time, tm3o_cost_population, tm3o_cost_map_index, tm3o_cost_seq;
static uint64_t tm3o_cost_marks[4];
static unsigned tm3o_cost_mark_mask;
static void TM3O_COST_Close(void) {
   if(tm3o_cost_file) { fclose(tm3o_cost_file); tm3o_cost_file=NULL; }
   tm3o_cost_enabled=tm3o_cost_active=0;
}
static void TM3O_COST_Clock(int32_t ts) {
   if(ts>=tm3o_cost_last_ts) tm3o_cost_cycles+=(uint32_t)(ts-tm3o_cost_last_ts);
   tm3o_cost_last_ts=ts;
}
static void TM3O_COST_FrameBegin(int32_t ts) { tm3o_cost_last_ts=ts; ++tm3o_cost_frames; }
static void TM3O_COST_FrameEnd(int32_t ts) { TM3O_COST_Clock(ts); }
static void TM3O_COST_Flush(void) {
   unsigned i;
   uint32_t population=TM3O_OC_Read(0x800D3234U);
   int valid=population==tm3o_cost_population && TM3O_OC_Read(0x800D2CC4U)==tm3o_cost_map_index &&
      TM3O_OC_Read(0x800D2D3CU)==0 && TM3O_OC_Read(0x800D2D40U)==3 && TM3O_OC_Read(0x800D2D50U)==0 &&
      TM3O_OC_Read(0x800895A8U)==tm3o_cost_start_time+1 && tm3o_cost_mark_mask==15;
   fprintf(tm3o_cost_file,"%u,%u,%u,%u,%u,%u,%u,%d,%llu,%llu,%llu,%llu,%u,%llu,%llu,%llu,%llu,",
      ++tm3o_cost_tick,tm3o_cost_seq,tm3o_cost_start_time,TM3O_OC_Read(0x800895A8U),
      tm3o_cost_population,population,tm3o_cost_map_index,valid,
      (unsigned long long)(tm3o_cost_total-tm3o_cost_start_total),
      (unsigned long long)(tm3o_cost_irqs-tm3o_cost_start_irqs),
      (unsigned long long)(tm3o_cost_cycles-tm3o_cost_start_cycles),
      (unsigned long long)(tm3o_cost_frames-tm3o_cost_start_frames),tm3o_cost_mark_mask,
      (unsigned long long)tm3o_cost_marks[0],(unsigned long long)tm3o_cost_marks[1],
      (unsigned long long)tm3o_cost_marks[2],(unsigned long long)tm3o_cost_marks[3]);
   for(i=0;i<TM3O_COST_FUNCTIONS;i++) if(tm3o_cost_counts[i])
      fprintf(tm3o_cost_file,"%u:%llu;",i,(unsigned long long)tm3o_cost_counts[i]);
   fputc('\n',tm3o_cost_file);
   if(fflush(tm3o_cost_file)!=0 || tm3o_cost_tick>=3000) TM3O_COST_Close();
}
static void TM3O_COST_Before(uint32_t pc,int32_t ts,uint32_t opf) {
   unsigned id=0, mark=4;
   if(!tm3o_cost_init) {
      const char *name=getenv("TM3O_GUEST_COST_FILE");
      tm3o_cost_init=1;
      if(name && *name) tm3o_cost_file=fopen(name,"wbx");
      if(tm3o_cost_file) {
         tm3o_cost_enabled=1; atexit(TM3O_COST_Close);
         fputs("tick,sequence_before,time_start,time_end,active_start,active_end,map,valid,dispatches,irq_dispatches,guest_cycle_span,frame_crossings,mark_mask,published_at,returned_at,update_done_at,render_done_at,function_counts\n",tm3o_cost_file);
         fflush(tm3o_cost_file);
         fprintf(stderr,"GUEST_COST_V1 active: %s; maximum 3000 intervals; host overhead affects wall timing\n",name);
      }
   }
   if(!tm3o_cost_enabled) return;
   TM3O_COST_Clock(ts);
   if(opf&0x80U) { ++tm3o_cost_irqs; return; }
   if(pc==0x8003AA90U) {
      if(tm3o_cost_active) TM3O_COST_Flush();
      if(!tm3o_cost_enabled) return;
      tm3o_cost_active=TM3O_OC_Read(0x800D2D40U)==3 && TM3O_OC_Read(0x800D2D3CU)==0 &&
         TM3O_OC_Read(0x800D2CB4U)!=0 && TM3O_OC_Read(0x800D2D50U)==0;
      memset(tm3o_cost_counts,0,sizeof(tm3o_cost_counts));
      memset(tm3o_cost_marks,0,sizeof(tm3o_cost_marks));tm3o_cost_mark_mask=0;
      tm3o_cost_start_time=TM3O_OC_Read(0x800895A8U);
      tm3o_cost_population=TM3O_OC_Read(0x800D3234U);
      tm3o_cost_map_index=TM3O_OC_Read(0x800D2CC4U);
      tm3o_cost_seq=TM3O_OC_Read(0x8004790CU);
      tm3o_cost_start_total=tm3o_cost_total;tm3o_cost_start_irqs=tm3o_cost_irqs;
      tm3o_cost_start_cycles=tm3o_cost_cycles;tm3o_cost_start_frames=tm3o_cost_frames;
   }
   if(!tm3o_cost_active) return;
   if(pc==0x80047AFCU)mark=0;
   if(pc==0x8003AA98U)mark=1;
   if(pc==0x8003AC18U)mark=2;
   if(pc==0x8003ACB4U)mark=3;
   if(mark<4 && !(tm3o_cost_mark_mask&(1U<<mark))) {
      tm3o_cost_marks[mark]=tm3o_cost_total-tm3o_cost_start_total;
      tm3o_cost_mark_mask|=1U<<mark;
   }
   if(pc>=0x80010000U && pc<0x80070000U && !(pc&3U))id=tm3o_cost_map[(pc-0x80010000U)/4];
   ++tm3o_cost_counts[id];++tm3o_cost_total;
}
#endif
