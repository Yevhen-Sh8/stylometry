Одна KPI-комірка — велике моно-число + мітка великими літерами. Викладіть кілька в сітку з проміжком 1px, щоб зібрати смугу статистики результатів.

```jsx
<div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:1,background:'var(--border-0)',border:'1px solid var(--border-1)',borderRadius:'var(--r-sm)',overflow:'hidden'}}>
  <StatCard value="14" label="Джерел" tone="info" />
  <StatCard value="3" label="Підозрілих пар" tone="danger" />
  <StatCard value="0.78" label="R DIMS"><GradeBadge grade="SS" /></StatCard>
</div>
```

- `tone` забарвлює лише число (danger/warn/ok/info). Значення завжди табличні моно.
- Проміжок 1px у сітці + спільний бордюр і Є роздільником — не додавайте бордюри самим карткам.
