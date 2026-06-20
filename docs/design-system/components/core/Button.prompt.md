Кнопка дії робочого середовища — primary/secondary/ghost у чотирьох розмірах; для будь-якої команди в операційному інтерфейсі.

```jsx
<Button variant="primary" onClick={run}>Запустити аналіз</Button>
<Button variant="ghost" size="sm">Очистити</Button>
<Button variant="secondary">Завантажити CSV</Button>
```

- `variant`: `default` (нейтральна заливка), `primary` (сигнально-синій CTA), `secondary`, `ghost` (прозора до ховера).
- `size`: `xs` (24px) · `sm` (28px) · `md` (32px, типовий) · `large` (44px, ціль дотику).
- Disabled падає до 35% непрозорості. Ховер поглиблює заливку на один bg-шар; ніколи без сяйва чи масштабу на звичайних кнопках.
