"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSelectedModel } from "@/hooks/use-selected-model";

export function ModelSelector({ disabled }: { disabled?: boolean }) {
  const { selected, setSelected, models } = useSelectedModel();
  if (!models.length || !selected) return null;
  const items = models.map((m) => ({ value: m.id, label: m.label }));
  return (
    <Select
      items={items}
      value={selected}
      onValueChange={(value) => typeof value === "string" && setSelected(value)}
      disabled={disabled}
    >
      <SelectTrigger size="sm" aria-label="Model" className="max-w-[11rem] border-none shadow-none">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {models.map((model) => (
          <SelectItem key={model.id} value={model.id}>
            <span className="flex flex-col">
              <span>{model.label}</span>
              <span className="text-xs text-muted-foreground">{model.description}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
