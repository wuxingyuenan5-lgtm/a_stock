function mmEscape(value){
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function mmNumber(value){
  if(value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function mmFormat(value, unit){
  const number = mmNumber(value);
  if(number === null) return '—';
  if(unit === '%') return `${(number * 100).toFixed(2)}%`;
  if(unit === '家') return `${Math.round(number).toLocaleString()} 家`;
  if(unit === '亿元') return `${number.toLocaleString(undefined,{maximumFractionDigits:2})} 亿元`;
  return `${number.toLocaleString(undefined,{maximumFractionDigits:4})}${unit ? ` ${unit}` : ''}`;
}

function mmAxisFormat(value, unit){
  if(unit === '%') return `${(value * 100).toFixed(1)}%`;
  if(unit === '家') return Math.round(value).toLocaleString();
  return Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
}

function mmDomain(series, startIndex, endIndex, axis, zeroLine){
  const values = [];
  series.filter(item => (item.axis || 'left') === axis).forEach(item => {
    (item.values || []).slice(startIndex,endIndex+1).forEach(value => {
      const number = mmNumber(value);
      if(number !== null) values.push(number);
    });
  });
  if(!values.length) return [-1,1];
  let min = Math.min(...values), max = Math.max(...values);
  if(zeroLine || series.some(item => (item.axis || 'left') === axis && (item.kind === 'bar' || item.kind === 'area'))){
    min = Math.min(0,min); max = Math.max(0,max);
  }
  if(min === max){
    const pad = Math.max(Math.abs(min) * .1, .01);
    min -= pad; max += pad;
  }else{
    const pad = (max-min) * .10;
    min -= pad; max += pad;
  }
  return [min,max];
}

function drawSvg(container,config,startIndex,endIndex,hiddenNames){
  const dates = config.dates || [];
  const palette = ['#2563eb','#ef4444','#10b981','#f97316','#8b5cf6','#0891b2','#db2777','#64748b'];
  const visibleSeries = (config.series || []).filter(item => !hiddenNames.has(item.name));
  if(!dates.length || !visibleSeries.length){
    container.innerHTML = '<div class="chart-empty">暂无可展示数据</div>';
    return;
  }
  const w=1120,h=390,ml=82,mr=config.rightAxis?92:42,mt=26,mb=58;
  const x0=ml,x1=w-mr,y0=mt,y1=h-mb;
  const count=Math.max(1,endIndex-startIndex+1);
  const xFor=index => count===1 ? (x0+x1)/2 : x0 + (x1-x0)*(index-startIndex)/(count-1);
  const leftDomain=mmDomain(visibleSeries,startIndex,endIndex,'left',!!config.zeroLine);
  const rightDomain=mmDomain(visibleSeries,startIndex,endIndex,'right',!!config.zeroLine);
  const yFor=(value,axis)=>{
    const domain=axis==='right'?rightDomain:leftDomain;
    return y1-(value-domain[0])/(domain[1]-domain[0])*(y1-y0);
  };
  let svg=`<svg class="chart-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${mmEscape(config.title||'时间序列图')}">`;
  for(let i=0;i<5;i++){
    const value=leftDomain[0]+(leftDomain[1]-leftDomain[0])*i/4;
    const y=yFor(value,'left');
    svg+=`<line x1="${x0}" y1="${y.toFixed(1)}" x2="${x1}" y2="${y.toFixed(1)}" stroke="#e2e8f0"/>`;
    svg+=`<text x="${x0-10}" y="${(y+4).toFixed(1)}" text-anchor="end" class="axis-label">${mmEscape(mmAxisFormat(value,(config.leftAxis||{}).unit||''))}</text>`;
    if(config.rightAxis){
      const rv=rightDomain[0]+(rightDomain[1]-rightDomain[0])*i/4;
      svg+=`<text x="${x1+10}" y="${(y+4).toFixed(1)}" text-anchor="start" class="axis-label">${mmEscape(mmAxisFormat(rv,(config.rightAxis||{}).unit||''))}</text>`;
    }
  }
  if(config.zeroLine && leftDomain[0] <= 0 && leftDomain[1] >= 0){
    const zy=yFor(0,'left');
    svg+=`<line x1="${x0}" y1="${zy.toFixed(1)}" x2="${x1}" y2="${zy.toFixed(1)}" stroke="#94a3b8" stroke-width="1.3"/>`;
  }
  if(config.leftAxis && config.leftAxis.title){
    svg+=`<text x="18" y="${(y0+y1)/2}" transform="rotate(-90 18 ${(y0+y1)/2})" text-anchor="middle" class="axis-title">${mmEscape(config.leftAxis.title)}${config.leftAxis.unit?`（${mmEscape(config.leftAxis.unit)}）`:''}</text>`;
  }
  if(config.rightAxis && config.rightAxis.title){
    svg+=`<text x="${w-14}" y="${(y0+y1)/2}" transform="rotate(90 ${w-14} ${(y0+y1)/2})" text-anchor="middle" class="axis-title">${mmEscape(config.rightAxis.title)}${config.rightAxis.unit?`（${mmEscape(config.rightAxis.unit)}）`:''}</text>`;
  }

  const barSeries=visibleSeries.filter(item=>item.kind==='bar');
  visibleSeries.forEach((series,seriesIndex)=>{
    const color=series.color||palette[seriesIndex%palette.length];
    const axis=series.axis||'left';
    const unit=series.unit||'';
    const values=series.values||[];
    if(series.kind==='bar'){
      const barIndex=barSeries.indexOf(series);
      const available=Math.max(3,(x1-x0)/Math.max(1,count)*.72);
      const barWidth=Math.max(1.5,Math.min(8,available/Math.max(1,barSeries.length)));
      for(let index=startIndex;index<=endIndex;index++){
        const value=mmNumber(values[index]); if(value===null) continue;
        const x=xFor(index)+(barIndex-(barSeries.length-1)/2)*barWidth;
        const y=yFor(value,axis),base=yFor(0,axis);
        const top=Math.min(y,base),height=Math.max(1,Math.abs(base-y));
        svg+=`<rect x="${(x-barWidth/2).toFixed(1)}" y="${top.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${height.toFixed(1)}" fill="${color}" opacity=".30"><title>${mmEscape(dates[index])} · ${mmEscape(series.name)} · ${mmEscape(mmFormat(value,unit))}</title></rect>`;
      }
      return;
    }
    const points=[];
    for(let index=startIndex;index<=endIndex;index++){
      const value=mmNumber(values[index]); if(value===null) continue;
      points.push({x:xFor(index),y:yFor(value,axis),index,value});
    }
    if(!points.length) return;
    const path=points.map((point,i)=>`${i?'L':'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
    if(series.kind==='area'){
      const baseline=yFor(Math.max(0,(axis==='right'?rightDomain:leftDomain)[0]),axis);
      const area=`M ${points[0].x.toFixed(1)} ${baseline.toFixed(1)} L ${points.map(p=>`${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' L ')} L ${points[points.length-1].x.toFixed(1)} ${baseline.toFixed(1)} Z`;
      svg+=`<path d="${area}" fill="${color}" opacity=".16" stroke="none"/>`;
    }
    svg+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
    points.forEach(point=>{
      svg+=`<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="2.6" fill="${color}"><title>${mmEscape(dates[point.index])} · ${mmEscape(series.name)} · ${mmEscape(mmFormat(point.value,unit))}</title></circle>`;
    });
  });

  const labelCount=Math.min(9,count);
  const indexes=[];
  for(let i=0;i<labelCount;i++) indexes.push(Math.round(startIndex+i*(endIndex-startIndex)/Math.max(1,labelCount-1)));
  [...new Set(indexes)].forEach(index=>{
    const anchor=index===startIndex?'start':index===endIndex?'end':'middle';
    svg+=`<text x="${xFor(index).toFixed(1)}" y="${h-22}" text-anchor="${anchor}" class="axis-label">${mmEscape((dates[index]||'').slice(5))}</text>`;
  });
  svg+='</svg>';
  container.innerHTML=svg;
}

function mountTimeChart(el,config){
  const dates=config.dates||[];
  const start=el.querySelector('.time-range-start');
  const end=el.querySelector('.time-range-end');
  const label=el.querySelector('.time-range-label');
  const allButton=el.querySelector('.time-range-all');
  const legend=el.querySelector('.time-chart-legend');
  const hiddenNames=new Set();
  start.min=end.min="0";
  start.max=end.max=String(Math.max(0,dates.length-1));
  start.value="0";
  end.value=String(Math.max(0,dates.length-1));

  function normalizedWindow(){
    let a=Number(start.value),b=Number(end.value);
    if(a>b){const temp=a;a=b;b=temp;}
    return [a,b];
  }
  function redraw(){
    const [a,b]=normalizedWindow();
    const visibleSeries=(config.series||[]).filter(item=>!hiddenNames.has(item.name));
    drawSvg(el.querySelector('.time-chart-canvas'),{...config,series:visibleSeries},a,b,new Set());
    label.textContent=dates.length?`${dates[a]} — ${dates[b]}`:'暂无数据';
  }
  if(legend){
    legend.innerHTML='';
    (config.series||[]).forEach((series,index)=>{
      const button=document.createElement('button');
      button.type='button'; button.className='chart-legend-item';
      button.innerHTML=`<span class="legend-swatch" style="background:${series.color||'#64748b'}"></span>${mmEscape(series.name)}`;
      button.addEventListener('click',()=>{
        if(hiddenNames.has(series.name)){hiddenNames.delete(series.name);button.classList.remove('muted');}
        else{hiddenNames.add(series.name);button.classList.add('muted');}
        redraw();
      });
      legend.appendChild(button);
    });
  }
  start.addEventListener('input',redraw);
  end.addEventListener('input',redraw);
  allButton.addEventListener('click',()=>{
    start.value="0";
    end.value=String(Math.max(0,dates.length-1));
    redraw();
  });
  redraw();
}

document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-time-chart="1"]').forEach(el=>{
    const node=el.querySelector('.time-chart-config');
    if(!node) return;
    try{mountTimeChart(el,JSON.parse(node.textContent));}
    catch(error){el.querySelector('.time-chart-canvas').innerHTML=`<div class="chart-empty">图表渲染失败：${mmEscape(error.message)}</div>`;}
  });
});
