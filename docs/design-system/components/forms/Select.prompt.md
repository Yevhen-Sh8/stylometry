Нативний випадний список, стилізований під поля DIMS, із власною кареткою.

```jsx
<Select label="Метод проєкції" value={m} onChange={e => setM(e.target.value)}
  options={[{value:'pca',label:'PCA (лінійна)'},{value:'mds',label:'MDS'},{value:'tsne',label:'t-SNE'}]} />
```

- Приймає об'єкти `{value,label}` або прості рядки.
- Та сама висота 36px / бордюр / кільце фокуса, що й `Input`. Уживайте для параметрів аналізу та коротких переліків.
