#!/usr/bin/env python3
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter

import excel_renderer_artifact as core
import run_excel_renderer_v12 as v12

core.VERSION = "1.3"

UP_BAR = "#F8DDCD"
DOWN_BAR = "#DDEED7"
LIMIT_UP_LINE = "#F00000"
LIMIT_DOWN_LINE = "#00A651"
BLUE = "#4F81BD"
RED = "#D9534F"
CYAN = "#28AFCB"
ORANGE = "#F28E2B"
DARK_BLUE = "#156082"
AXIS = "#777777"
ZERO = "#9A9A9A"
TEXT = "#222222"


def _font() -> None:
    for path in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"):
        if Path(path).exists():
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=path).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def _clean_axes(ax, *, right: bool = False) -> None:
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.spines["bottom"].set_linewidth(1.0)
    ax.spines["left"].set_visible(not right)
    ax.spines["right"].set_visible(right)
    if right:
        ax.spines["right"].set_color(AXIS); ax.spines["right"].set_linewidth(1.0); ax.spines["left"].set_visible(False)
    else:
        ax.spines["left"].set_color(AXIS); ax.spines["left"].set_linewidth(1.0); ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", colors="#444444", labelsize=9, length=3, width=0.8)
    ax.tick_params(axis="x", pad=7)
    ax.margins(x=0.01)


def _ticks(ax, labels, every=10, rotation=45):
    idx = list(range(0, len(labels), every))
    if labels and len(labels)-1 not in idx: idx.append(len(labels)-1)
    ax.set_xticks(idx); ax.set_xticklabels([labels[i] for i in idx], rotation=rotation, ha="right")


def _fig(figsize=(14.2,5.4), top=0.80, bottom=0.19):
    _font(); fig, ax = plt.subplots(figsize=figsize, dpi=160); fig.patch.set_facecolor("white"); fig.subplots_adjust(left=0.075,right=0.925,top=top,bottom=bottom); return fig, ax


def _tmp(name):
    root = Path(tempfile.gettempdir()) / "a_stock_renderer_v13"; root.mkdir(parents=True, exist_ok=True); return str(root/name)


def _market_structure(labels, up, down, lu, ld, path):
    fig, ax = _fig((14.2,6.2),0.81,0.20); x=list(range(len(labels)))
    ax.bar(x,up,width=0.62,color=UP_BAR,edgecolor="none",zorder=1); ax.bar(x,[-v if v is not None else None for v in down],width=0.62,color=DOWN_BAR,edgecolor="none",zorder=1)
    vals=[abs(v) for v in up+down if v is not None]; lim=max(500,math.ceil(max(vals)/500)*500); ax.set_ylim(-lim,lim); ax.axhline(0,color=ZERO,lw=1.0,zorder=3); _clean_axes(ax); _ticks(ax,labels,9,60); ax.set_ylabel("上涨 / 下跌家数（左轴）",fontsize=10,color="#555555",labelpad=10)
    ax2=ax.twinx(); ax2.plot(x,lu,color=LIMIT_UP_LINE,lw=2.1,zorder=4); ax2.plot(x,[-v if v is not None else None for v in ld],color=LIMIT_DOWN_LINE,lw=2.1,zorder=4)
    vals2=[abs(v) for v in lu+ld if v is not None]; lim2=max(50,math.ceil(max(vals2)/50)*50); ax2.set_ylim(-lim2,lim2); _clean_axes(ax2,right=True); ax2.set_ylabel("涨停 / 跌停家数（右轴）",fontsize=10,color="#555555",labelpad=10); ax2.set_xticks([])
    fig.suptitle("市场涨跌结构｜上涨/下跌家数 + 涨停/跌停家数",fontsize=15,fontweight="bold",color=TEXT,y=0.965)
    fig.legend(handles=[Patch(facecolor=UP_BAR,label="上涨家数（左轴，正值）"),Patch(facecolor=DOWN_BAR,label="下跌家数（左轴，负值）"),Line2D([0],[0],color=LIMIT_UP_LINE,lw=2.2,label="涨停（右轴，正值）"),Line2D([0],[0],color=LIMIT_DOWN_LINE,lw=2.2,label="跌停（右轴，负值）")],loc="upper center",bbox_to_anchor=(0.5,0.915),ncol=4,frameon=False,fontsize=10)
    fig.savefig(path,bbox_inches="tight",facecolor="white"); plt.close(fig)


def _single_signed(labels,pos,neg,title,pos_name,neg_name,path,lines=False):
    fig,ax=_fig((14.2,5.2),0.82,0.20);x=list(range(len(labels)));nneg=[-v if v is not None else None for v in neg]
    if lines:
        ax.plot(x,pos,color=LIMIT_UP_LINE,lw=2.0,label=pos_name);ax.plot(x,nneg,color=LIMIT_DOWN_LINE,lw=2.0,label=neg_name);step=50
    else:
        ax.bar(x,pos,width=0.62,color=UP_BAR,edgecolor="none",label=pos_name);ax.bar(x,nneg,width=0.62,color=DOWN_BAR,edgecolor="none",label=neg_name);step=500
    vals=[abs(v) for v in pos+neg if v is not None];lim=max(step,math.ceil(max(vals)/step)*step);ax.set_ylim(-lim,lim);ax.axhline(0,color=ZERO,lw=1.0);_clean_axes(ax);_ticks(ax,labels,10,50)
    fig.suptitle(title,fontsize=15,fontweight="bold",y=0.955);fig.legend(loc="upper center",bbox_to_anchor=(0.5,0.90),ncol=2,frameon=False,fontsize=10);fig.savefig(path,bbox_inches="tight",facecolor="white");plt.close(fig)


def _width(labels,values,path):
    fig,ax=_fig((14.2,4.6),0.80,0.22);x=list(range(len(labels)));ax.plot(x,values,color=DARK_BLUE,lw=2.0);ax.axhline(0,color=ZERO,lw=0.9);_clean_axes(ax);_ticks(ax,labels,10,45);ax.yaxis.set_major_formatter(PercentFormatter(1.0,decimals=0));fig.suptitle("市场宽度",fontsize=15,fontweight="bold",y=0.95);fig.savefig(path,bbox_inches="tight",facecolor="white");plt.close(fig)


def _area_line(labels,area,line,title,area_label,line_label,path,line_percent=True):
    fig,ax=_fig();x=list(range(len(labels)));ax.fill_between(x,area,0,color=BLUE,alpha=0.94,zorder=1);_clean_axes(ax);_ticks(ax,labels,10,45);ax.yaxis.set_major_formatter(PercentFormatter(1.0,decimals=0));ax.set_ylabel(f"{area_label}（左轴）",fontsize=10,labelpad=10,color="#555555");ax.set_ylim(bottom=0)
    ax2=ax.twinx();ax2.plot(x,line,color=RED,lw=2.0,zorder=3);_clean_axes(ax2,right=True);ax2.set_ylabel(f"{line_label}（右轴）",fontsize=10,labelpad=10,color="#555555");ax2.set_xticks([]);ax2.set_ylim(bottom=0)
    if line_percent: ax2.yaxis.set_major_formatter(PercentFormatter(1.0,decimals=0))
    fig.suptitle(title,fontsize=15,fontweight="bold",color=TEXT,y=0.96);fig.legend(handles=[Patch(facecolor=BLUE,label=f"{area_label}（面积，左轴）"),Line2D([0],[0],color=RED,lw=2.0,label=f"{line_label}（折线，右轴）")],loc="upper center",bbox_to_anchor=(0.5,0.912),ncol=2,frameon=False,fontsize=10);fig.savefig(path,bbox_inches="tight",facecolor="white");plt.close(fig)


def _bar_line(labels,bars,line,title,bar_label,line_label,path):
    fig,ax=_fig();x=list(range(len(labels)));ax.bar(x,bars,width=0.62,color=CYAN,edgecolor="none",zorder=1);_clean_axes(ax);_ticks(ax,labels,10,45);ax.set_ylabel(f"{bar_label}（左轴）",fontsize=10,labelpad=10,color="#555555");ax.set_ylim(bottom=0)
    ax2=ax.twinx();ax2.plot(x,line,color=ORANGE,lw=2.0,zorder=3);_clean_axes(ax2,right=True);ax2.yaxis.set_major_formatter(PercentFormatter(1.0,decimals=0));ax2.set_ylabel(f"{line_label}（右轴）",fontsize=10,labelpad=10,color="#555555");ax2.set_xticks([]);ax2.set_ylim(bottom=0)
    fig.suptitle(title,fontsize=15,fontweight="bold",color=TEXT,y=0.96);fig.legend(handles=[Patch(facecolor=CYAN,label=f"{bar_label}（柱状，左轴）"),Line2D([0],[0],color=ORANGE,lw=2.0,label=f"{line_label}（折线，右轴）")],loc="upper center",bbox_to_anchor=(0.5,0.912),ncol=2,frameon=False,fontsize=10);fig.savefig(path,bbox_inches="tight",facecolor="white");plt.close(fig)


def _add_image(sh,path,row,col,width,height): sh.images.add({"path":path,"anchor":{"from":{"row":row,"col":col},"extent":{"widthPx":width,"heightPx":height}}})


def rebuild_03(wb,rows):
    sh=wb.worksheets.get_item("03_市场宽度图");sh.delete_all_drawings();cats=[core.as_date(x["date"]).strftime("%m-%d") for x in rows];up=[x["up"] for x in rows];down=[x["down"] for x in rows];lu=[x["lu"] for x in rows];ld=[x["ld"] for x in rows];width=[x["width"] for x in rows]
    p1,p2,p3=_tmp("03_advance_decline.png"),_tmp("03_limit.png"),_tmp("03_width.png");_single_signed(cats,up,down,"上涨与下跌家数｜上涨为正、下跌为负","上涨家数","下跌家数",p1);_single_signed(cats,lu,ld,"涨停与跌停｜涨停为正、跌停为负","涨停","跌停",p2,lines=True);_width(cats,width,p3);_add_image(sh,p1,4,0,1120,430);_add_image(sh,p2,28,0,1120,430);_add_image(sh,p3,52,0,1120,360)


def rebuild_05(wb):
    sh=wb.worksheets.get_item("05_申万行业资金拥挤度");n=core.nrows(sh,63,1000);rows=sorted(sh.get_range(f"A63:P{62+n}").values if n else [],key=lambda r:r[0] or 0);sh.delete_all_drawings();sh.get_range("A4:P57").clear({"contentsOnly":True});comm=[r for r in rows if r[2] not in (None,"") and r[3] not in (None,"")];four=[r for r in rows if r[13] not in (None,"") and r[14] not in (None,"")];p1,p2=_tmp("05_communication.png"),_tmp("05_four.png");_area_line([core.as_date(r[0]).strftime("%m-%d") for r in comm],[r[3] for r in comm],[r[2] for r in comm],"通信设备｜成交额占全A与换手率","通信设备成交额占全A","通信设备换手率",p1);_bar_line([core.as_date(r[0]).strftime("%m-%d") for r in four],[r[13] for r in four],[r[14] for r in four],"四行业｜成交额与成交额占比","四行业成交额合计（亿元）","四行业成交额占全A",p2);_add_image(sh,p1,3,0,1240,500);_add_image(sh,p2,30,0,1240,500)


def rebuild_07(wb,innovation):
    if not innovation:return
    sh=wb.worksheets.get_item("07_创新药交易拥挤度");sh.delete_all_drawings();sh.get_range("A4:H28").clear({"contentsOnly":True});rows=sorted(innovation["rows"],key=lambda r:r["date"])
    if innovation["has_turnover"]: valid=[r for r in rows if r["share"] is not None and r["turnover"] is not None];line=[r["turnover"] for r in valid];label="创新药换手率";pct=True
    else: valid=[r for r in rows if r["share"] is not None and r["activity"] is not None];line=[r["activity"] for r in valid];label="20日成交量活跃度代理";pct=False
    p=_tmp("07_innovation.png");_area_line([r["date"][5:] for r in valid],[r["share"] for r in valid],line,"创新药｜成交额占全A与换手率","创新药成交额占全A",label,p,line_percent=pct);_add_image(sh,p,3,0,1000,500)


def rebuild_00(wb,payload,market_rows,innovation):
    sh=wb.worksheets.get_item("00_市场总览");sh.delete_all_drawings();sh.get_range("Q1:AE96").clear({"contentsOnly":True});sh.merge_cells("Q1:AE1");sh.get_range("Q1").values=[["关键走势图总览｜Renderer v1.3"]];sh.get_range("Q1:AE1").format.fill="#17365D";sh.get_range("Q1:AE1").format.font={"bold":True,"size":15,"color":"#FFFFFF"};sh.get_range("Q1:AE1").format.horizontal_alignment="center"
    cats=[core.as_date(x["date"]).strftime("%m-%d") for x in market_rows];up=[x["up"] for x in market_rows];down=[x["down"] for x in market_rows];lu=[x["lu"] for x in market_rows];ld=[x["ld"] for x in market_rows];width=[x["width"] for x in market_rows]
    p1,p2=_tmp("00_market.png"),_tmp("00_width.png");_market_structure(cats,up,down,lu,ld,p1);_width(cats,width,p2);_add_image(sh,p1,1,16,1080,470);_add_image(sh,p2,23,16,1080,330)
    s05=wb.worksheets.get_item("05_申万行业资金拥挤度");n05=core.nrows(s05,63,1000);r05=sorted(s05.get_range(f"A63:P{62+n05}").values if n05 else [],key=lambda r:r[0] or 0);comm=[r for r in r05 if r[2] not in (None,"") and r[3] not in (None,"")];four=[r for r in r05 if r[13] not in (None,"") and r[14] not in (None,"")]
    pc,pf=_tmp("00_comm.png"),_tmp("00_four.png");_area_line([core.as_date(r[0]).strftime("%m-%d") for r in comm],[r[3] for r in comm],[r[2] for r in comm],"通信设备｜成交额占全A与换手率","通信设备成交额占全A","通信设备换手率",pc);_bar_line([core.as_date(r[0]).strftime("%m-%d") for r in four],[r[13] for r in four],[r[14] for r in four],"四行业｜成交额与成交额占比","四行业成交额合计（亿元）","四行业成交额占全A",pf);_add_image(sh,pc,40,16,1080,385);_add_image(sh,pf,60,16,1080,385)
    if innovation:
        rows=sorted(innovation["rows"],key=lambda r:r["date"])
        if innovation["has_turnover"]: valid=[r for r in rows if r["share"] is not None and r["turnover"] is not None];vals=[r["turnover"] for r in valid];label="创新药换手率";pct=True
        else: valid=[r for r in rows if r["share"] is not None and r["activity"] is not None];vals=[r["activity"] for r in valid];label="20日成交量活跃度代理";pct=False
        pi=_tmp("00_innovation.png");_area_line([r["date"][5:] for r in valid],[r["share"] for r in valid],vals,"创新药｜成交额占全A与换手率","创新药成交额占全A",label,pi,line_percent=pct);_add_image(sh,pi,80,16,1080,385)
    for col in ["Q","R","S","T","U","V","W","X","Y","Z","AA","AB","AC","AD","AE"]:sh.get_range(f"{col}:{col}").format.column_width=10

v12._rebuild_03_charts=rebuild_03
v12._rebuild_05_charts=rebuild_05
v12._rebuild_07_charts=rebuild_07
v12._rebuild_00_charts=rebuild_00


def main():
    v12.install();core.main()

if __name__=="__main__":main()
