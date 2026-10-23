/* Host-only lifecycle observer. Uses ObjectCause's side-effect-free RAM reads.
 * No MMIO, GPR/guest writes, emulated clock adjustment or forced transitions.
 * Samples pre-dispatch state, retaining the pending load separately.
 */
#ifndef TM3O_LIFECYCLE_TRACE_H
#define TM3O_LIFECYCLE_TRACE_H
#ifndef TM3O_LC_PERIOD
#define TM3O_LC_PERIOD 1048576U
#endif
#ifndef TM3O_LC_LIMIT
#define TM3O_LC_LIMIT 65536U
#endif
static FILE *tm3o_lc_file;
static int tm3o_lc_init, tm3o_lc_stopped, tm3o_lc_armed;
static uint64_t tm3o_lc_dispatches;
static uint32_t tm3o_lc_records, tm3o_lc_remaining=TM3O_LC_PERIOD;
static const uint32_t tm3o_lc_globals[32]={
   0x800D2D1C,0x800D2D3C,0x800D2D40,0x800D2D44,
   0x800D2D48,0x800D2D4C,0x800D2D50,0x800D2D54,
   0x800D2D58,0x800D2D60,0x800D2D68,0x800D2D6C,
   0x800D2D7C,0x800D2D84,0x800D2CB0,0x800D2CB4,
   0x800D2CB8,0x800D2CBC,0x800D2CC0,0x800D2CC4,
   0x800D3298,0x800895A8,0x80089BC8,0x8004790C,
   0x80047904,0x800896BC,0x800896C0,0x800D3234,
   0x800D3238,0x800D323C,0x800D3280,0x800D3294};

static void TM3O_LC_Close(void)
{
   if(tm3o_lc_file) { fclose(tm3o_lc_file); tm3o_lc_file=NULL; }
   tm3o_lc_stopped=1;
}
static int TM3O_LC_Event(uint32_t pc)
{
   switch(pc) {
   case 0x800444C8U: case 0x8003A2C4U: case 0x80044E5CU:
   case 0x80048CA4U: case 0x800518C8U: case 0x800475B4U:
   case 0x80017C30U: case 0x8003AB9CU: case 0x8003ABC0U:
      return 1;
   default: break;
   }
   if(!tm3o_lc_armed) return 0;
   switch(pc) {
   case 0x8004A38CU: case 0x8004A3DCU: case 0x8004A4A4U:
   case 0x8004A4F0U: case 0x80017CD4U: case 0x80017CDCU:
   case 0x80047D3CU: case 0x80047F18U:
      return 1;
   default: return 0;
   }
}
static void TM3O_LC_Before(uint32_t pc,uint32_t timestamp,uint32_t ld,
                           uint32_t ldval,uint32_t instr,uint32_t opf)
{
   uint32_t r[128],i,kind;
   if(tm3o_lc_stopped || (opf&0x80U) || !MainRAM) return;
   if(!tm3o_lc_init) {
      const char *name=getenv("TM3O_LIFECYCLE_TRACE_FILE");
      uint32_t h[4]={0x31434C54U,1U,512U,TM3O_LC_PERIOD};
      tm3o_lc_init=1;
      if(!name || !*name) { tm3o_lc_stopped=1; return; }
      /* C11 exclusive creation: never overwrite a previous capture. */
      tm3o_lc_file=fopen(name,"wbx");
      if(!tm3o_lc_file) { tm3o_lc_stopped=1;
         fprintf(stderr,"LIFECYCLE_TRACE disabled: output exists/unavailable\n"); return; }
      atexit(TM3O_LC_Close);
      if(fwrite(h,sizeof(h),1,tm3o_lc_file)!=1 || fflush(tm3o_lc_file)!=0) {
         TM3O_LC_Close(); return;
      }
      fprintf(stderr,"LIFECYCLE_TRACE_V1 active: %s; host-only, sampled after linked menu exit\n",name);
   }
   ++tm3o_lc_dispatches;
   if(pc==0x800444C8U && TM3O_OC_Read(0x800D2D68U)!=0 &&
      TM3O_OC_Read(0x800D2CB4U)!=0) tm3o_lc_armed=1;
   /* Pause -> Quit reaches this same outer loop without the victory timer.
    * Capture it as a shorter diagnostic, not as proof of the tournament case. */
   if(pc==0x8003A2C4U && TM3O_OC_Read(0x800D2CB4U)!=0 &&
      (TM3O_OC_Read(0x800D2D44U)==4 || TM3O_OC_Read(0x800D2D44U)==1))
      tm3o_lc_armed=1;
   kind=TM3O_LC_Event(pc)?1U:0U;
   if(tm3o_lc_armed && --tm3o_lc_remaining==0) {
      kind|=2U; tm3o_lc_remaining=TM3O_LC_PERIOD;
   }
   if(!kind) return;
   memset(r,0,sizeof(r));
   r[0]=kind; r[1]=pc; r[2]=timestamp; r[3]=ld; r[4]=ldval;
   r[5]=instr; r[6]=opf; r[7]=(uint32_t)tm3o_lc_dispatches;
   r[8]=(uint32_t)(tm3o_lc_dispatches>>32);
   for(i=0;i<32;i++) { r[10+i]=GPR[i]; r[42+i]=TM3O_OC_Read(tm3o_lc_globals[i]); }
   r[9]|=TM3O_OC_Block(r+74,GPR[29],32)?1U:0U;
   r[9]|=TM3O_OC_Block(r+106,GPR[4],16)?2U:0U;
   r[122]=(uint32_t)tm3o_lc_armed;
   if(fwrite(r,sizeof(r),1,tm3o_lc_file)!=1 || fflush(tm3o_lc_file)!=0) {
      fprintf(stderr,"LIFECYCLE_TRACE write failed; stopped\n"); TM3O_LC_Close(); return;
   }
   if(++tm3o_lc_records>=TM3O_LC_LIMIT) {
      fprintf(stderr,"LIFECYCLE_TRACE record limit; stopped, game unchanged\n");
      TM3O_LC_Close();
   }
}
#endif
