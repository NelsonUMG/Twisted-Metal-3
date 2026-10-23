/* Read-only sparse phase observer. Same hook API as GuestCost, no histogram.
 * Phase spans include IRQ/events and are guest cycles, not host CPU cost. */
#ifndef TM3O_PACING_H
#define TM3O_PACING_H
static FILE *pace_file;
static int pace_init,pace_enabled,pace_active;
static int32_t pace_last;
static uint64_t pace_cycles,pace_frames,pace_start,pace_frame_start;
static uint64_t pace_marks[6],pace_frame_marks[6];
static unsigned pace_mask,pace_rows;
static uint32_t pace_time,pace_pop,pace_map,pace_seq;
static uint32_t pace_entry_count,pace_entry_ready,pace_target,pace_release_count;
static void TM3O_COST_Close(void) {
 if(pace_file) {fclose(pace_file);pace_file=NULL;}
 pace_enabled=pace_active=0;
}
static void pace_clock(int32_t ts) {
 if(ts>=pace_last)pace_cycles+=(uint32_t)(ts-pace_last);
 pace_last=ts;
}
static void TM3O_COST_FrameBegin(int32_t ts) {pace_last=ts;++pace_frames;}
static void TM3O_COST_FrameEnd(int32_t ts) {pace_clock(ts);}
static int pace_scene(void) {
 return TM3O_OC_Read(0x800D2D40U)==3 && TM3O_OC_Read(0x800D2D3CU)==0 &&
 TM3O_OC_Read(0x800D2CB4U)!=0 && TM3O_OC_Read(0x800D2D50U)==0;
}
static void pace_flush(void) {
 unsigned i;
 uint32_t end=TM3O_OC_Read(0x800895A8U),pop=TM3O_OC_Read(0x800D3234U);
 int valid=pace_scene() && pop==pace_pop && TM3O_OC_Read(0x800D2CC4U)==pace_map &&
 end==pace_time+1U && pace_mask==63;
 fprintf(pace_file,"%u,%u,%u,%u,%u,%u,%u,%d,%u,%llu,%llu",
 ++pace_rows,pace_seq,pace_time,end,pace_pop,pop,pace_map,valid,pace_mask,
 (unsigned long long)(pace_cycles-pace_start),(unsigned long long)(pace_frames-pace_frame_start));
 for(i=0;i<6;i++)fprintf(pace_file,",%llu",(unsigned long long)pace_marks[i]);
 for(i=0;i<6;i++)fprintf(pace_file,",%llu",(unsigned long long)pace_frame_marks[i]);
 fprintf(pace_file,",%u,%u,%u,%u\n",pace_entry_count,pace_entry_ready,pace_target,pace_release_count);
 if(fflush(pace_file)!=0 || pace_rows>=6000)TM3O_COST_Close();
}
static void TM3O_COST_Before(uint32_t pc,int32_t ts,uint32_t opf) {
 unsigned mark=6;
 if(!pace_init) {
  const char *name=getenv("TM3O_PACING_FILE");pace_init=1;
  if(name && *name)pace_file=fopen(name,"wbx");
  if(pace_file) {
   pace_enabled=1;atexit(TM3O_COST_Close);
   fputs("tick,sequence_before,time_start,time_end,active_start,active_end,map,valid,mask,cycles,frames,publish,link_return,world_done,gate_entry,gate_ready,render_done,publish_frame,link_return_frame,world_done_frame,gate_entry_frame,gate_ready_frame,render_done_frame,entry_counter,entry_signal,target_counter,release_counter\n",pace_file);
   fflush(pace_file);fprintf(stderr,"PACING_V1 active: %s; max 6000 intervals; no guest writes\n",name);
  }
 }
 if(!pace_enabled || (opf&0x80U))return;
 switch(pc) {
 case 0x8003AA90U: break;
 case 0x80047AFCU: mark=0;break;
 case 0x8003AA98U: mark=1;break;
 case 0x8003AC18U: mark=2;break;
 case 0x8003E084U: mark=3;break;
 case 0x8003E0D4U: mark=4;break;
 case 0x8003ACB4U: mark=5;break;
 default:return;
 }
 pace_clock(ts);
 if(pc==0x8003AA90U) {
  if(pace_active)pace_flush();
  if(!pace_enabled)return;
  pace_active=pace_scene();pace_start=pace_cycles;pace_frame_start=pace_frames;
  pace_time=TM3O_OC_Read(0x800895A8U);pace_pop=TM3O_OC_Read(0x800D3234U);
  pace_map=TM3O_OC_Read(0x800D2CC4U);pace_seq=TM3O_OC_Read(0x8004790CU);
  pace_mask=0;memset(pace_marks,0,sizeof(pace_marks));memset(pace_frame_marks,0,sizeof(pace_frame_marks));
  pace_entry_count=pace_entry_ready=pace_target=pace_release_count=0;
 }
 if(!pace_active || mark>=6 || (pace_mask&(1U<<mark)))return;
 pace_marks[mark]=pace_cycles-pace_start;pace_frame_marks[mark]=pace_frames-pace_frame_start;
 pace_mask|=1U<<mark;
 if(mark==3) {
  pace_entry_count=TM3O_OC_Read(0x8007E9D8U);pace_entry_ready=TM3O_OC_Read(0x8007E9DCU);
  pace_target=TM3O_OC_Read(0x800D2D48U)==2?3:2;
 }
 if(mark==4)pace_release_count=TM3O_OC_Read(0x8007E9D8U);
}
#endif
