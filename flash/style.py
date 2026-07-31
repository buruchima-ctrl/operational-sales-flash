# -*- coding: utf-8 -*-
"""The stylesheet — one file, one home, no external assets.

Every page on the site links this and nothing else. Keeping it in its own
module rather than buried in the renderer makes that literal: there is exactly
one place a colour, a size or a rule can be changed, and a renderer that wants
a new look has to come here rather than inline a style attribute.

Three constraints shape every decision below:

  * **No network.** No webfont, no CDN, no image. Every family falls back
    through faces that ship with macOS, Windows and Linux, so the page renders
    identically offline and on a reviewer's machine.
  * **The portfolio's colour semantics are load-bearing**, not decoration.
    Gold means an input the business asserted, blue a figure presented as
    given, green something this system calculated. A colour is never chosen
    because it looks nice in a place where it would say something untrue.
  * **Deterministic output.** No random, no clock, no user-agent branching.

Within those, this is a designed document rather than a styled one: a modular
type scale, a four-pixel vertical rhythm, tabular figures everywhere a number
can be compared to the number above it, and tables built for scanning down a
column rather than for filling a page.
"""

CSS = """/* ========================================================================
   Lumière Ops Flash — the operational site.
   Tokens: gold = an INPUT the business asserted · blue = a PRESENTATION,
   a figure shown as given · green = a CALCULATION this system performed.
   ===================================================================== */

:root{
  /* -- surface & ink ------------------------------------------------- */
  --paper:#F6F4EF;      --paper-2:#EFEBE3;
  --panel:#FFFFFF;      --panel-2:#FBFAF7;
  --ink:#18242F;        --ink-2:#3D4C59;   --soft:#6B7885;  --faint:#98A2AC;
  --rule:#D8D2C7;       --rule-soft:#EAE6DD;  --rule-hair:#F2EFE9;

  /* -- semantic tokens ------------------------------------------------ */
  --gold:#8A6416;  --gold-bg:#FBF3E1;  --gold-edge:#E3D2A8;
  --blue:#2C5F8A;  --blue-bg:#E9F0F7;  --blue-edge:#BBD0E2;
  --calc:#2A7355;  --calc-bg:#E6F2EC;  --calc-edge:#B4D8C6;
  --bad:#A33A2A;   --bad-bg:#FBEBE7;   --bad-edge:#E8C2B8;
  --good:#2A7355;

  /* -- type ------------------------------------------------------------ */
  --display:'Avenir Next','Avenir','Segoe UI Variable Display','Segoe UI',
            system-ui,'Helvetica Neue',Helvetica,Arial,sans-serif;
  --body:'Charter','Iowan Old Style','Palatino Linotype','Book Antiqua',
         Georgia,'Times New Roman',serif;
  --data:ui-monospace,'SF Mono','SFMono-Regular','JetBrains Mono',Menlo,
         Consolas,'DejaVu Sans Mono','Courier New',monospace;

  /* modular scale, ratio 1.22 from a 15.5px body */
  --fs-3xs:9.5px; --fs-2xs:10.5px; --fs-xs:11.5px; --fs-sm:12.5px;
  --fs-base:15.5px; --fs-md:17px; --fs-lg:19.5px; --fs-xl:24px;
  --fs-2xl:29px; --fs-3xl:35px;

  /* four-pixel vertical rhythm */
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:22px;
  --sp-6:30px; --sp-7:40px; --sp-8:56px;

  --track:.13em;         /* eyebrow letter-spacing */
  --maxw:1120px;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--body);font-size:var(--fs-base);line-height:1.6;
  font-kerning:normal;text-rendering:optimizeLegibility;
  -webkit-font-smoothing:antialiased;
}
::selection{background:var(--gold-bg)}

a{color:var(--blue);text-decoration:none;
  border-bottom:1px solid rgba(44,95,138,.28);
  transition:border-color .12s ease,background-color .12s ease;}
a:hover{border-bottom-color:var(--blue);background:rgba(44,95,138,.06)}
a:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-bottom:none}

.wrap{max-width:var(--maxw);margin:0 auto;padding:var(--sp-5) var(--sp-4) var(--sp-8);}
.wrap.narrow{max-width:820px}

/* -- masthead ---------------------------------------------------------- */
header.top{
  border-bottom:2px solid var(--ink);
  padding-bottom:var(--sp-3);margin:0 0 var(--sp-5);
}
.eyebrow{
  font-family:var(--display);font-size:var(--fs-xs);letter-spacing:var(--track);
  text-transform:uppercase;color:var(--soft);font-weight:600;
  display:inline-block;
}
h1{
  font-family:var(--display);font-size:var(--fs-2xl);font-weight:600;
  margin:var(--sp-2) 0 0;line-height:1.1;letter-spacing:-.015em;
  color:var(--ink);
}
.meta{
  font-family:var(--data);font-size:var(--fs-sm);color:var(--soft);
  margin-top:var(--sp-2);letter-spacing:.01em;
}
.crumbs{
  font-family:var(--display);font-size:var(--fs-sm);color:var(--soft);
  margin:0 0 var(--sp-3);letter-spacing:.01em;
}
.crumbs a{border-bottom:none;color:var(--soft)}
.crumbs a:hover{color:var(--blue);background:none}
.crumbs span.sep{padding:0 var(--sp-2);color:var(--rule)}

/* -- section headings -------------------------------------------------- */
h2{
  font-family:var(--display);font-size:var(--fs-xs);letter-spacing:var(--track);
  text-transform:uppercase;color:var(--ink-2);font-weight:700;
  border-top:1px solid var(--rule);padding-top:var(--sp-3);
  margin:var(--sp-7) 0 var(--sp-3);position:relative;
}
h2::after{
  content:"";position:absolute;top:-1px;left:0;width:34px;height:2px;
  background:var(--ink);
}
h3{
  font-family:var(--display);font-size:var(--fs-md);font-weight:600;
  margin:var(--sp-5) 0 var(--sp-2);letter-spacing:-.005em;color:var(--ink);
}

/* -- persona navigation ------------------------------------------------ */
nav.personas{
  display:flex;flex-wrap:wrap;gap:2px;margin:0 0 var(--sp-4);
  border-bottom:1px solid var(--rule);padding-bottom:0;
}
nav.personas a{
  font-family:var(--display);font-size:var(--fs-sm);font-weight:500;
  padding:var(--sp-2) var(--sp-3);color:var(--soft);
  border:1px solid transparent;border-bottom:none;
  border-radius:2px 2px 0 0;margin-bottom:-1px;background:none;
}
nav.personas a:hover{color:var(--ink);background:var(--panel-2)}
nav.personas a.on{
  color:var(--ink);font-weight:700;background:var(--panel);
  border-color:var(--rule);border-bottom:1px solid var(--panel);
}

/* -- KPI tiles --------------------------------------------------------- */
.tiles{display:flex;flex-wrap:wrap;gap:var(--sp-2);margin:var(--sp-1) 0 var(--sp-5);}
.tile{
  flex:1 1 158px;background:var(--panel);
  border:1px solid var(--rule-soft);border-top:2px solid var(--rule);
  padding:var(--sp-3) var(--sp-3) var(--sp-3);min-width:0;
}
.tile .eyebrow{font-size:var(--fs-2xs);color:var(--soft);font-weight:600}
.tile .v{
  font-family:var(--data);font-size:var(--fs-xl);font-weight:600;
  line-height:1.1;font-variant-numeric:tabular-nums lining-nums;
  padding-top:var(--sp-1);letter-spacing:-.02em;color:var(--ink);
}
.tile .s{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--soft);
  padding-top:var(--sp-1);line-height:1.35;
  font-variant-numeric:tabular-nums;
}
.tile.sm .v{font-size:var(--fs-lg)}
.tile .v.good{color:var(--good)} .tile .v.bad{color:var(--bad)}
.tile .v.calc{color:var(--calc)}

.bad{color:var(--bad)} .good{color:var(--good)} .calc{color:var(--calc)}
.gold{color:var(--gold)} .blue{color:var(--blue)} .soft{color:var(--soft)}

/* -- banners ----------------------------------------------------------- */
.band{
  border:1px solid var(--gold-edge);border-left:3px solid var(--gold);
  background:var(--gold-bg);padding:var(--sp-3) var(--sp-3);
  margin:0 0 var(--sp-2);font-size:var(--fs-sm);line-height:1.55;
  color:var(--ink-2);
}
.band.alert{border-color:var(--bad-edge);border-left-color:var(--bad);background:var(--bad-bg)}
.band.note{border-color:var(--blue-edge);border-left-color:var(--blue);background:var(--blue-bg)}
.band.calcband{border-color:var(--calc-edge);border-left-color:var(--calc);background:var(--calc-bg)}
.band .t{
  font-family:var(--display);font-size:var(--fs-2xs);letter-spacing:.11em;
  text-transform:uppercase;font-weight:700;display:block;
  margin-bottom:var(--sp-1);
}
.band .t.g{color:var(--gold)} .band .t.r{color:var(--bad)}
.band .t.b{color:var(--blue)} .band .t.c{color:var(--calc)}
.band b{font-family:var(--data);font-variant-numeric:tabular-nums;
  font-weight:600;color:var(--ink)}

/* -- narrative --------------------------------------------------------- */
.narr{
  font-size:var(--fs-md);line-height:1.65;margin:var(--sp-3) 0 var(--sp-4);
  color:var(--ink);max-width:66ch;
}

/* -- tables ------------------------------------------------------------ */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;
  border:1px solid var(--rule-soft);background:var(--panel);
  margin-bottom:var(--sp-2);}
table{width:100%;border-collapse:collapse;font-size:var(--fs-sm);
  background:var(--panel);}
th{
  font-family:var(--display);font-size:var(--fs-3xs);letter-spacing:.09em;
  text-transform:uppercase;color:var(--soft);font-weight:700;text-align:right;
  padding:var(--sp-2) var(--sp-3);border-bottom:1.5px solid var(--ink-2);
  white-space:nowrap;background:var(--panel-2);vertical-align:bottom;
}
th:first-child{text-align:left}
td{
  font-family:var(--data);font-variant-numeric:tabular-nums lining-nums;
  text-align:right;padding:var(--sp-2) var(--sp-3);
  border-bottom:1px solid var(--rule-hair);white-space:nowrap;
  color:var(--ink-2);
}
td:first-child{
  font-family:var(--body);text-align:left;white-space:normal;
  color:var(--ink);padding-right:var(--sp-4);
}
tbody tr:hover td,table tr:hover td{background:var(--panel-2)}
tr:last-child td{border-bottom:none}
tr.tot td{
  font-weight:700;color:var(--ink);background:var(--panel-2);
  border-top:1.5px solid var(--ink-2);border-bottom:none;
}
table.tier th.grp{
  text-align:center;color:var(--ink);letter-spacing:.07em;
  font-size:var(--fs-2xs);background:var(--paper-2);
  border-bottom:1px solid var(--rule);
}
th[title],td[title],.hint{cursor:help;
  text-decoration:underline dotted var(--faint);text-underline-offset:3px;}
th[title]{border-bottom:1.5px solid var(--ink-2)}

/* -- lists: focus and exceptions --------------------------------------- */
ul.focus,ul.exc{list-style:none;margin:0;padding:0;}
ul.focus li{
  padding:var(--sp-2) 0;border-bottom:1px solid var(--rule-hair);
  font-size:var(--fs-base);line-height:1.5;
}
ul.focus li:last-child{border-bottom:none}
ul.focus .mk{font-weight:700;padding-right:var(--sp-1);font-family:var(--display)}
ul.focus .rc{
  display:block;font-family:var(--data);font-size:var(--fs-xs);
  color:var(--soft);padding-left:var(--sp-5);padding-top:2px;
  font-variant-numeric:tabular-nums;
}
ul.exc li{
  padding:var(--sp-3) 0 var(--sp-3);border-bottom:1px solid var(--rule-hair);
}
ul.exc li:last-child{border-bottom:none}
ul.exc .h{
  font-family:var(--display);font-size:var(--fs-base);font-weight:600;
  line-height:1.4;color:var(--ink);
}
ul.exc .h span:first-child{font-family:var(--data);padding-right:var(--sp-1)}
ul.exc .d{
  font-size:var(--fs-sm);color:var(--soft);line-height:1.55;
  padding-top:2px;max-width:78ch;
}
ul.exc .r{
  font-family:var(--data);font-size:var(--fs-3xs);color:var(--gold);
  border:1px solid var(--gold-edge);background:var(--gold-bg);
  padding:1px 4px;margin-left:var(--sp-2);border-radius:2px;
  letter-spacing:.04em;vertical-align:1px;
}
.recon{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--calc);
  padding:var(--sp-2) 0 var(--sp-3);line-height:1.55;
  border-left:2px solid var(--calc-edge);padding-left:var(--sp-3);
  margin:var(--sp-2) 0 var(--sp-4);
}

/* -- store-status funnel ------------------------------------------------ */
.funnel{display:flex;flex-wrap:wrap;gap:var(--sp-2);align-items:stretch;
  margin:0 0 var(--sp-3);}
.funnel .f{
  flex:1 1 128px;background:var(--panel);border:1px solid var(--rule-soft);
  border-top:2px solid var(--blue-edge);padding:var(--sp-2) var(--sp-3);
}
.funnel .f .n{
  font-family:var(--data);font-size:var(--fs-lg);font-weight:600;
  font-variant-numeric:tabular-nums;color:var(--ink);line-height:1.2;
}
.funnel .f .l{
  font-family:var(--display);font-size:var(--fs-3xs);letter-spacing:.1em;
  text-transform:uppercase;color:var(--soft);font-weight:600;
}
.funnel .arrow{align-self:center;color:var(--faint);font-size:var(--fs-md)}

.keyrow{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--soft);
  margin:0 0 var(--sp-3);display:flex;flex-wrap:wrap;gap:var(--sp-4);
}
.keyrow i{font-style:normal}
.tri{font-style:normal;padding-right:3px}
.tri.up{color:var(--good)} .tri.dn{color:var(--bad)} .tri.mid{color:var(--faint)}

/* -- cards ------------------------------------------------------------- */
.grid2{display:flex;flex-wrap:wrap;gap:var(--sp-4)}
.grid2 > *{flex:1 1 340px;min-width:0}
.cards{display:flex;flex-wrap:wrap;gap:var(--sp-2);}
.card{
  flex:1 1 250px;background:var(--panel);border:1px solid var(--rule-soft);
  border-left:2px solid var(--blue-edge);
  padding:var(--sp-3) var(--sp-3);font-size:var(--fs-sm);
  color:var(--soft);line-height:1.5;
}
.card .n{
  font-family:var(--display);font-size:var(--fs-3xs);letter-spacing:.1em;
  text-transform:uppercase;color:var(--faint);font-weight:700;
}
.card .h{
  font-family:var(--display);font-size:var(--fs-base);font-weight:600;
  margin:2px 0 var(--sp-1);color:var(--ink);
}
.card .h a{border-bottom:none}

/* -- SVG figures -------------------------------------------------------- */
svg.viz{
  display:block;max-width:100%;height:auto;background:var(--panel);
  border:1px solid var(--rule-soft);
}
.vizrow{display:flex;flex-wrap:wrap;gap:var(--sp-3)}
.vizrow figure{margin:0;flex:1 1 268px;min-width:0}
figcaption{
  font-family:var(--body);font-size:var(--fs-xs);color:var(--soft);
  padding-top:var(--sp-2);line-height:1.5;
}
.legendkeys{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--soft);
  padding-top:var(--sp-2);display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-3);
}
.legendkeys i{font-style:normal;white-space:nowrap}
.sw{display:inline-block;width:9px;height:9px;margin-right:5px;
  vertical-align:baseline;border-radius:1px}

details.rank{
  background:var(--panel);border:1px solid var(--rule-soft);
  padding:var(--sp-2) var(--sp-3);margin-top:var(--sp-2);
  font-size:var(--fs-sm);
}
details.rank summary{
  font-family:var(--display);font-size:var(--fs-sm);cursor:pointer;
  color:var(--blue);font-weight:600;letter-spacing:.01em;
}
details.rank[open] summary{margin-bottom:var(--sp-2)}

/* -- KPI tree ----------------------------------------------------------- */
.tree{display:flex;flex-wrap:wrap;gap:var(--sp-2);align-items:stretch;
  margin:var(--sp-2) 0 var(--sp-3)}
.tree .node{
  flex:1 1 172px;background:var(--panel);border:1px solid var(--rule-soft);
  border-top:2px solid var(--calc-edge);padding:var(--sp-3);min-width:0;
}
.tree .node.op{
  flex:0 0 26px;display:flex;align-items:center;justify-content:center;
  border:none;background:none;font-family:var(--data);font-size:var(--fs-lg);
  color:var(--faint);padding:0;
}
.tree .node .l{
  font-family:var(--display);font-size:var(--fs-3xs);letter-spacing:.1em;
  text-transform:uppercase;color:var(--soft);font-weight:700;
}
.tree .node .v{
  font-family:var(--data);font-size:var(--fs-lg);font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-.015em;color:var(--ink);
  line-height:1.25;
}
.tree .node .c{font-family:var(--data);font-size:var(--fs-xs);
  font-variant-numeric:tabular-nums;line-height:1.45}

.calcbox{
  background:var(--calc-bg);border:1px solid var(--calc-edge);
  border-top:2px solid var(--calc);padding:var(--sp-4);margin:var(--sp-3) 0;
}
.calcbox label{
  display:block;font-family:var(--display);font-size:var(--fs-2xs);
  letter-spacing:.09em;text-transform:uppercase;color:var(--ink-2);
  font-weight:700;margin-top:var(--sp-3);
}
.calcbox input[type=range]{width:100%;max-width:360px;accent-color:var(--calc);
  margin-top:var(--sp-1)}
.calcbox output{font-family:var(--data);font-variant-numeric:tabular-nums;
  color:var(--calc);font-weight:600}
.calcbox .out{
  font-family:var(--data);font-size:var(--fs-2xl);font-weight:600;
  padding-top:var(--sp-3);letter-spacing:-.02em;color:var(--ink);
  font-variant-numeric:tabular-nums;
}
.calcbox .chk{font-family:var(--data);font-size:var(--fs-xs);color:var(--calc);
  padding-top:var(--sp-2);line-height:1.5}
.calcbox button{
  font-family:var(--display);font-size:var(--fs-sm);font-weight:600;
  padding:var(--sp-2) var(--sp-3);border:1px solid var(--calc);
  background:var(--panel);color:var(--calc);cursor:pointer;border-radius:2px;
}
.calcbox button:hover{background:var(--calc);color:var(--panel)}

/* -- hourly bars --------------------------------------------------------- */
.hours{
  display:flex;align-items:flex-end;gap:3px;height:168px;
  padding:var(--sp-3) var(--sp-3) var(--sp-2);background:var(--panel);
  border:1px solid var(--rule-soft);
}
.hours .h{flex:1 1 0;display:flex;flex-direction:column;justify-content:flex-end;
  align-items:center;height:100%;min-width:0}
.hours .h .b{width:100%;background:var(--blue);min-height:1px;border-radius:1px 1px 0 0}
.hours .h .b2{width:100%;background:var(--gold);min-height:1px;opacity:.55;
  border-radius:1px 1px 0 0;margin-bottom:1px}
.hours .h .t{font-family:var(--data);font-size:var(--fs-3xs);color:var(--soft);
  padding-top:var(--sp-1);font-variant-numeric:tabular-nums}
.hours .h:hover .b{background:var(--ink)}

/* -- fiscal-week grid ---------------------------------------------------- */
.periodhead{
  font-family:var(--display);font-size:var(--fs-sm);letter-spacing:.1em;
  text-transform:uppercase;color:var(--gold);font-weight:700;
  margin:var(--sp-5) 0 var(--sp-2);
}
table.cal{table-layout:fixed;font-size:var(--fs-sm);}
table.cal th{text-align:center;background:var(--panel-2)}
table.cal th.wk{text-align:left;width:118px}
table.cal td{
  text-align:left;vertical-align:top;padding:0;white-space:normal;
  border:1px solid var(--rule-hair);height:78px;
}
table.cal tr:hover td{background:none}
table.cal td.wk{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--soft);
  padding:var(--sp-2) var(--sp-3);border-left:none;vertical-align:middle;
  background:var(--panel-2);
}
.cell{display:block;padding:var(--sp-2);height:100%;border-bottom:none;
  transition:background .12s ease}
a.cell:hover{background:var(--blue-bg);border-bottom:none}
.cell .dnum{font-family:var(--data);font-size:var(--fs-2xs);color:var(--faint);}
.cell .amt{
  font-family:var(--data);font-size:var(--fs-base);font-weight:600;
  font-variant-numeric:tabular-nums;display:block;padding-top:1px;
  color:var(--ink);letter-spacing:-.015em;
}
.cell .cmp{font-family:var(--data);font-size:var(--fs-2xs);display:block;
  font-variant-numeric:tabular-nums}
.cell.empty{background:repeating-linear-gradient(135deg,transparent,
  transparent 6px,var(--rule-hair) 6px,var(--rule-hair) 7px);}
.flag{
  display:inline-block;font-family:var(--display);font-size:var(--fs-3xs);
  letter-spacing:.06em;text-transform:uppercase;padding:0 3px;
  margin:2px 2px 0 0;border:1px solid var(--gold);color:var(--gold);
  border-radius:2px;font-weight:600;
}
.flag.r{border-color:var(--bad);color:var(--bad)}
.flag.b{border-color:var(--blue);color:var(--blue)}
.flag.c{border-color:var(--calc);color:var(--calc)}

/* -- prose blocks --------------------------------------------------------- */
.disc{font-size:var(--fs-sm);line-height:1.6;margin:0 0 var(--sp-2);
  color:var(--ink-2);max-width:84ch;}
.disc b{
  font-family:var(--data);color:var(--gold);font-weight:700;
  font-size:var(--fs-xs);padding-right:var(--sp-1);letter-spacing:.02em;
}
.key{
  font-family:var(--data);font-size:var(--fs-xs);line-height:1.6;
  color:var(--soft);margin:0 0 var(--sp-2);max-width:88ch;
}
.key b{color:var(--ink);font-weight:600}
.key a{font-family:var(--display);font-size:var(--fs-sm)}
.legend{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--soft);
  border-top:1px solid var(--rule);padding-top:var(--sp-2);
  margin-top:var(--sp-5);line-height:1.6;
}
.legend i{font-style:normal;font-weight:600}
footer{
  font-family:var(--data);font-size:var(--fs-xs);color:var(--faint);
  border-top:1px solid var(--rule);margin-top:var(--sp-5);
  padding-top:var(--sp-3);line-height:1.65;max-width:88ch;
}
.pager{
  display:flex;justify-content:space-between;font-family:var(--display);
  font-size:var(--fs-sm);margin-top:var(--sp-5);padding-top:var(--sp-3);
  border-top:1px solid var(--rule-soft);
}
.pager a{border-bottom:none;font-weight:600}

/* -- responsive ----------------------------------------------------------- */
@media (max-width:760px){
  :root{--fs-base:15px;--fs-2xl:25px;--fs-xl:21px}
  .wrap{padding:var(--sp-3) var(--sp-3) var(--sp-7)}
  .tile{flex:1 1 140px}
  .tree .node{flex:1 1 140px}
  .tree .node.op{flex:0 0 100%;height:18px}
  nav.personas{gap:0}
  nav.personas a{padding:var(--sp-2)}
}
@media print{
  body{background:#fff}
  nav.personas,.pager{display:none}
  .scroll{overflow:visible;border:none}
  a{color:var(--ink);border-bottom:none}
}
"""
