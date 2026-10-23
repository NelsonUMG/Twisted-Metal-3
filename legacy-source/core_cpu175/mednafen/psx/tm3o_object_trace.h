/* Read-only interpreter observer. All records are host memory/files, never guest
 * RAM. Pre-instruction register state: pending load is deliberately NOT applied.
 * Excludes interrupted dispatches, which made older PC hooks double-count.
 */
#ifndef TM3O_OBJECT_TRACE_H
#define TM3O_OBJECT_TRACE_H
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#ifndef TM3O_OC_LIMIT
#define TM3O_OC_LIMIT 65536U
#endif
static FILE *tm3o_oc_file;
static int tm3o_oc_init, tm3o_oc_stopped;
static uint64_t tm3o_oc_count;
static uint32_t tm3o_oc_boundary,tm3o_oc_reason=1;
static uint32_t (*tm3o_oc_ring)[256];

static int TM3O_OC_Interested(uint32_t pc)
{
   switch(pc) {
   case 0x80028C7CU: case 0x80028E9CU: case 0x80028EDCU:
   case 0x80030B90U: case 0x80030BB0U:
   case 0x8002EBFCU: case 0x8002EC20U: case 0x8002EC98U:
   case 0x8002ECC4U: case 0x8002ECCCU: case 0x8002ED64U:
   case 0x8002E79CU: case 0x8004AACCU: case 0x8004AAE4U:
   case 0x8004A38CU: case 0x8004A4F0U: case 0x8004A668U:
   case 0x8004AB6CU: case 0x8003A0F0U: case 0x8003A118U:
   case 0x8003AA74U: case 0x8003AA98U:
   case 0x8003AB9CU: case 0x8003ABC0U: return 1;
   default: return 0;
   }
}

static int TM3O_OC_Valid(uint32_t address, uint32_t bytes)
{
   uint32_t off=address & 0x1FFFFFFFU;
   if((address>=0x20000000U && address<0x80000000U) || address>=0xC0000000U || !bytes) return 0;
   if(off<0x01000000U && bytes<=0x01000000U-off) return MainRAM!=NULL;
   return address<0xA0000000U && ScratchRAM!=NULL && off>=0x1F800000U && off<0x1F800400U &&
          bytes<=0x1F800400U-off;
}
static uint32_t TM3O_OC_Read(uint32_t address)
{
   uint32_t off=address & 0x1FFFFFFFU, v=0, i;
   if(!TM3O_OC_Valid(address,4)) return 0;
   for(i=0;i<4;i++)
      v|=(uint32_t)(off>=0x1F800000U ? MASMEM_ReadU8(ScratchRAM,(off+i)&0x3FFU)
                                    : MASMEM_ReadU8(MainRAM,off+i)) << (i*8);
   return v;
}
static int TM3O_OC_Block(uint32_t *out,uint32_t address,uint32_t words)
{
   uint32_t i;
   if(!TM3O_OC_Valid(address,4*words)) return 0;
   for(i=0;i<words;i++) out[i]=TM3O_OC_Read(address+4*i);
   return 1;
}
static int TM3O_OC_Object(uint32_t pointer)
{
   uint32_t off=pointer & 0x1FFFFFFFU;
   return pointer<0xC0000000U && off>=0x10030U && off<=0x00FFFEA0U;
}
static void TM3O_OC_Close(void)
{
   if(tm3o_oc_file) {
      uint32_t retained=(uint32_t)(tm3o_oc_count<TM3O_OC_LIMIT?tm3o_oc_count:TM3O_OC_LIMIT),i;
      uint64_t start=tm3o_oc_count-retained;
      uint32_t h[8]={0x31434F54U,2U,1024U,TM3O_OC_LIMIT,
                     (uint32_t)tm3o_oc_count,(uint32_t)(tm3o_oc_count>>32),tm3o_oc_reason,retained};
      int ok=fwrite(h,sizeof(h),1,tm3o_oc_file)==1;
      for(i=0;i<retained && ok;i++)
         ok=fwrite(tm3o_oc_ring[(start+i)%TM3O_OC_LIMIT],1024,1,tm3o_oc_file)==1;
      if(fflush(tm3o_oc_file)!=0)ok=0;
      fclose(tm3o_oc_file); tm3o_oc_file=NULL;
      fprintf(stderr,"OBJECT_CAUSE dump reason=%u retained=%u total=%llu result=%s\n",
              tm3o_oc_reason,retained,(unsigned long long)tm3o_oc_count,ok?"OK":"WRITE_FAILED");
   }
   free(tm3o_oc_ring); tm3o_oc_ring=NULL;
   tm3o_oc_stopped=1;
}
static void TM3O_OC_Before(uint32_t pc,uint32_t timestamp,uint32_t ld,uint32_t ldval,
                           uint32_t instr,uint32_t opf)
{
   static const uint32_t globals[24]={
      0x800895A8,0x80089BC8,0x800D3298,0x800D2CB0,0x800D2CB4,0x800D2CB8,
      0x800D2CBC,0x800D2CC0,0x800D3234,0x800D3238,0x800D323C,0x800D3240,
      0x800D3244,0x800D3248,0x800D324C,0x800D3250,0x800D3254,0x800D3258,
      0x800D325C,0x800896BC,0x800896C0,0x80089B3C,0x800D2D34,0x8004790C};
   uint32_t r[256]={0}, obj=0,target=0,desc=0,i,mask=0;
   /* These target PCs are not COP2. IPCache means interrupt dispatch instead
    * of executing this instruction. Do not count that visit as execution. */
   if(tm3o_oc_stopped || (opf&0x80U) || !TM3O_OC_Interested(pc) || !MainRAM) return;
   if(!tm3o_oc_init) {
      const char *name=getenv("TM3O_OBJECT_TRACE_FILE");
      FILE *existing;
      tm3o_oc_init=1;
      if(!name || !*name) { tm3o_oc_stopped=1; return; }
      existing=fopen(name,"rb");
      if(existing) { fclose(existing); tm3o_oc_stopped=1;
         fprintf(stderr,"OBJECT_CAUSE disabled: refusing existing output\n"); return; }
      tm3o_oc_file=fopen(name,"wb");
      if(!tm3o_oc_file) { tm3o_oc_stopped=1; fprintf(stderr,"OBJECT_CAUSE output unavailable\n"); return; }
      tm3o_oc_ring=(uint32_t (*)[256])malloc((size_t)TM3O_OC_LIMIT*sizeof(r));
      if(!tm3o_oc_ring) { fclose(tm3o_oc_file);tm3o_oc_file=NULL;tm3o_oc_stopped=1;
         fprintf(stderr,"OBJECT_CAUSE ring allocation failed\n");return; }
      setvbuf(tm3o_oc_file,NULL,_IOFBF,1024*1024);
      atexit(TM3O_OC_Close);
      fprintf(stderr,"OBJECT_CAUSE_V1 active: %s; rolling host ring=64MiB; dump on game mismatch\n",name);
   }
   if(pc==0x8003AA74U) ++tm3o_oc_boundary;
   switch(pc) {
   case 0x80028E9CU: case 0x80030B90U: case 0x8002EBFCU: case 0x8004A668U: obj=GPR[4]; break;
   case 0x80028EDCU: case 0x80030BB0U: obj=GPR[16]; break;
   case 0x80028C7CU:
      if(GPR[31]==0x80028EF0U || GPR[31]==0x80030BB8U) obj=GPR[16];
      break;
   case 0x8002EC20U: case 0x8002EC98U: case 0x8002ECC4U:
   case 0x8002ECCCU: case 0x8002ED64U: obj=GPR[18]; break;
   case 0x8004AACCU: case 0x8004AAE4U: obj=GPR[16]+0x30; break;
   case 0x8004A4F0U: obj=GPR[2]; break;
   default: break;
   }
   desc=TM3O_OC_Read(GPR[28]+0x67CU);
   if(TM3O_OC_Object(obj)) {
      mask|=TM3O_OC_Block(r+64,obj-0x30,100)?2:0;
      target=TM3O_OC_Read(obj+0xA4);
      if(TM3O_OC_Object(target)) mask|=TM3O_OC_Block(r+164,target-0x30,28)?4:0;
   }
   mask|=TM3O_OC_Block(r+48,GPR[29],16)?1:0;
   if(TM3O_OC_Object(desc)) mask|=TM3O_OC_Block(r+192,desc,24)?8:0;
   if(GPR[4]>=0x10000U) mask|=TM3O_OC_Block(r+240,GPR[4],8)?16:0;
   mask|=TM3O_OC_Block(r+248,GPR[29]+0x40,8)?32:0;
   r[0]=1; r[1]=pc; r[2]=timestamp; r[3]=tm3o_oc_boundary;
   r[4]=TM3O_OC_Read(0x800895A8); r[5]=TM3O_OC_Read(0x80089BC8);
   r[6]=TM3O_OC_Read(0x8004790C); r[7]=TM3O_OC_Read(0x80047904);
   r[8]=ld; r[9]=ldval; r[10]=instr; r[11]=TM3O_OC_Read(0x80F00010);
   r[12]=obj; r[13]=target; r[14]=desc; r[15]=mask;
   for(i=0;i<32;i++) r[16+i]=GPR[i];
   for(i=0;i<24;i++) r[216+i]=TM3O_OC_Read(globals[i]);
   memcpy(tm3o_oc_ring[tm3o_oc_count%TM3O_OC_LIMIT],r,sizeof(r));
   ++tm3o_oc_count;
   if(pc==0x8003AB9CU || pc==0x8003ABC0U) {
      tm3o_oc_reason=pc==0x8003AB9CU?2:3;
      TM3O_OC_Close();
   }
}
#endif
