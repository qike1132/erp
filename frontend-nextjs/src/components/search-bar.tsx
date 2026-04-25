"use client";

import { SearchIcon, XIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClear?: () => void;
  placeholder?: string;
}

export function SearchBar({
  value,
  onChange,
  onSubmit,
  onClear,
  placeholder = "搜索...",
}: SearchBarProps) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="flex gap-2"
    >
      <div className="relative flex-1 max-w-xs">
        <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="plush-input pl-9"
        />
      </div>
      <Button type="submit" variant="secondary" className="rounded-xl">
        搜索
      </Button>
      {value && onClear && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClear}
          className="rounded-xl"
        >
          <XIcon className="h-4 w-4" />
        </Button>
      )}
    </form>
  );
}
