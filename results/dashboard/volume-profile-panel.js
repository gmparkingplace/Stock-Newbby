function renderVolumeProfile(){
 const f=frameOf(curSym()),box=document.getElementById('volumeProfileRows');if(!box)return;
 const data=f?VolumeProfile.build(f.candles,asOfIdx()):null;box.replaceChildren();
 if(!data){document.getElementById('volumeProfileSummary').textContent='매물대 계산에 필요한 봉이 부족해요.';document.getElementById('volumeProfileBasis').textContent='10개 이상의 유효한 봉이 필요해요.';return;}
 const peaks=data.bins.filter(b=>b.peak);
 document.getElementById('volumeProfileSummary').textContent=peaks.length?'거래 집중 추정 구간: '+peaks.map(b=>fmtP(b.low)+' ~ '+fmtP(b.high)).join(', '):'거래량이 없어 집중 구간을 확인할 수 없어요.';
 document.getElementById('volumeProfileBasis').textContent=`${fmtT(data.from)} ~ ${fmtT(data.to)} · ${data.count}개 ${tfWord()} · 선택일 이전의 불러온 전체 자료 기준. 확대·이동으로 바뀌지 않아요.`;
 for(const b of [...data.bins].reverse()){
  const row=document.createElement('tr');if(b.peak)row.className='vpPeak';
  const price=document.createElement('td'),share=document.createElement('td'),vol=document.createElement('td');
  price.textContent=`${fmtP(b.low)} ~ ${fmtP(b.high)}${b.peak?' · 거래 집중':''}`;
  const bar=document.createElement('span');bar.className='vpBar';bar.style.width=(b.share*100)+'%';bar.setAttribute('aria-hidden','true');
  share.append(bar,document.createTextNode((b.share*100).toFixed(1)+'%'));
  vol.textContent=b.volume.toLocaleString('ko-KR');row.append(price,share,vol);box.appendChild(row);
 }
}
document.addEventListener('DOMContentLoaded',renderVolumeProfile);
