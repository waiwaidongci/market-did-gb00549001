import {plot} from '../components/common/chart.js';
import {feedback} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW, STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

export async function results(route, refresh) {
  const {spec,runs,datasets} = workspace;
  const id = route.id || runs[0]?.id;
  if (!id) return panel(spec.pages[3],empty('还没有可查看的运行结果。','#run','前往运行'));
  const job = await workspace.getRun(id);
  const source = datasets.find(item => item.id === job.dataset_id);
  const message = feedback();
  const finished = item => item.status === 'complete' || item.status === 'failed';
  if (!finished(job)) {
    const original = location.hash;
    const status = el('p',{role:'status'},'后台正在计算，完成后会自动展示。');
    poll(()=>workspace.getRun(id),finished,()=>location.hash===original)
      .then(result=>{if (result && status.isConnected && location.hash===original) refresh();
        else if(status.isConnected) status.textContent='仍在执行，请点击刷新检查。';})
      .catch(error=>{if(status.isConnected) status.textContent=error.message;});
    return panel(job.name,pill(STATUS[job.status],job.status),status,button('刷新',{class:'quiet',onClick:refresh}));
  }
  const download = button('下载结果 CSV',{class:'quiet','data-testid':'export',onClick:event=>
    handler(download,message,()=>workspace.download(`/runs/${job.id}/export`,`${spec.short_name}-${job.id}.csv`))(event)});
  const history = el('label',{class:'field run-picker',for:'run-picker'},el('span',{},'切换运行记录'),
    el('select',{id:'run-picker',onChange:event=>{location.hash=`#results/${event.target.value}`;}},
      (runs.some(item=>item.id===job.id) ? runs : [job,...runs]).map(item=>el('option',{value:item.id,selected:item.id===job.id},item.name))));
  const result = job.result;
  const permutation = result && result.permutation;
  const ready = Boolean(permutation && permutation.complete);
  const analysis = result ? (ready
    ? el('section',{class:'analysis','data-testid':'analysis-complete'},
      el('div',{class:'result-head'},p(job.name,'eyeline'),h(2,result.headline),p(result.note,'intro-copy'),
        el('div',{class:'actions'},pill(STATUS[job.status],job.status),download,message)),
      panel('配对置换计数',
        metrics([
          {label:'实测等权双重差分（分钟）', value:permutation.observed, detail:'各配对双重差分的等权平均。'},
          {label:'绝对值不小于实测值的分配数', value:permutation.count, detail:'各对独立交换身份，平局计入。'},
          {label:'分配总数', value:permutation.total, detail:`共 ${permutation.pairs.length} 对完整配对，总数恒为 2 的配对数次方。`},
          {label:'置换比例', value:permutation.ratio, detail:'精确双侧置换比例，越小表示实测差分越极端。'},
        ]),
        table([
          {key:'pair', label:'配对'}, {key:'treated', label:'试点市场'},
          {key:'control', label:'对照市场'}, {key:'effect', label:'配对双重差分（分钟）'},
        ], permutation.pairs, {caption:'参与置换的配对'}),
        permutation.excluded?.length ? table([
          {key:'pair', label:'配对'}, {key:'reason', label:'整对剔除说明'},
        ], permutation.excluded, {caption:'整对剔除说明'}) : null),
      metrics(result.metrics),
      result.charts.map(plot),
      (result.sections || []).map(item=>panel(item.title,p(item.text))),
      result.tables.map(item=>panel(item.title,table(item.columns,item.rows,{caption:item.title}))))
    : el('section',{class:'analysis'},
      el('div',{class:'result-head'},p(job.name,'eyeline'),pill(STATUS[job.status],job.status),message),
      panel('配对置换计数',p('置换计数尚未算齐，配对、实测差分和计数暂不提供。','feedback'))))
    : panel(job.name,pill(STATUS[job.status],job.status),p(job.error,'feedback'),link('返回调整参数',`#run/${job.dataset_id}`,{class:'quiet'}));
  const inputs = spec.params.map(param=>el('div',{},el('dt',{},param.label),el('dd',{},value(job.params[param.key]))));
  return el('div',{},el('div',{class:'two-col'},el('div',{class:'wide-panel'},analysis),
    el('aside',{class:'sidebar-panel'},panel('运行来源',history,
      source && link(source.name,`#inputs/${source.id}`),p(date(job.finished_at),'subtle'),
      el('dl',{class:'dictionary'},inputs)),
    result && panel(spec.decision, pill(REVIEW[job.review],job.review),
      link('打开复核记录',`#review/${job.id}`,{class:'quiet'})))));
}
