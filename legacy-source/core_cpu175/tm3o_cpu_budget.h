/* Fixed emulated CPU budget for the 175% semiproduction distribution. */
#ifndef TM3O_CPU_BUDGET_H
#define TM3O_CPU_BUDGET_H
#include <stdlib.h>
#include <string.h>

static int tm3o_budget_percent(void)
{
 /* Ignore environment overrides: direct launches and both peers must agree. */
 const char *standard=getenv("TM3O_STANDARD_PS1");
 return standard && strcmp(standard,"1")==0 ? 100 : 175;
}
#endif
