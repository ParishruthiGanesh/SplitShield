"use client";

/** Recharts wrappers fed exclusively from analysis results. */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SEVERITY_COLORS } from "./ui";

const AXIS = { fill: "#93a4bc", fontSize: 12 };
const GRID = "#24314d";
const TOOLTIP_STYLE = {
  backgroundColor: "#16213a",
  border: "1px solid #24314d",
  borderRadius: 8,
  color: "#e6edf6",
} as const;

export function SplitDistributionChart({
  perSplitClass,
  classes,
}: {
  perSplitClass: Record<string, Record<string, number>>;
  classes: string[];
}) {
  const palette = ["#22d3ee", "#a78bfa", "#34d399", "#f59e0b", "#f472b6", "#818cf8"];
  const data = Object.entries(perSplitClass).map(([split, byClass]) => ({
    split,
    ...byClass,
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="split" tick={AXIS} axisLine={{ stroke: GRID }} />
        <YAxis tick={AXIS} axisLine={{ stroke: GRID }} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#ffffff10" }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {classes.map((cls, i) => (
          <Bar
            key={cls}
            dataKey={cls}
            stackId="a"
            fill={palette[i % palette.length]}
            radius={i === classes.length - 1 ? [3, 3, 0, 0] : undefined}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ClassDistributionChart({
  perClass,
}: {
  perClass: Record<string, number>;
}) {
  const data = Object.entries(perClass).map(([label, count]) => ({ label, count }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} layout="vertical" margin={{ left: 12 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={AXIS} axisLine={{ stroke: GRID }} allowDecimals={false} />
        <YAxis type="category" dataKey="label" tick={AXIS} width={90} axisLine={{ stroke: GRID }} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#ffffff10" }} />
        <Bar dataKey="count" fill="#22d3ee" radius={[0, 3, 3, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SeverityChart({ counts }: { counts: Record<string, number> }) {
  const order = ["critical", "high", "medium", "low"];
  const data = order.map((severity) => ({ severity, count: counts[severity] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="severity" tick={AXIS} axisLine={{ stroke: GRID }} />
        <YAxis tick={AXIS} axisLine={{ stroke: GRID }} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#ffffff10" }} />
        <Bar dataKey="count" radius={[3, 3, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.severity} fill={SEVERITY_COLORS[d.severity]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AccuracyComparisonChart({
  original,
  cleaned,
}: {
  original: { accuracy: number; low?: number; high?: number };
  cleaned: { accuracy: number; low?: number; high?: number };
}) {
  const data = [
    { name: "Original test set", accuracy: +(original.accuracy * 100).toFixed(2) },
    { name: "Leakage-quarantined", accuracy: +(cleaned.accuracy * 100).toFixed(2) },
  ];
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" margin={{ left: 40 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tick={AXIS} unit="%" axisLine={{ stroke: GRID }} />
        <YAxis type="category" dataKey="name" tick={AXIS} width={140} axisLine={{ stroke: GRID }} />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${v}%`, "accuracy"]} cursor={{ fill: "#ffffff10" }} />
        <Bar dataKey="accuracy" radius={[0, 3, 3, 0]}>
          <Cell fill="#f59e0b" />
          <Cell fill="#34d399" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
