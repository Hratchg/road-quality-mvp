import { useState, useRef, useEffect } from "react";
import { useNominatim, NominatimResult } from "../hooks/useNominatim";

interface AddressInputProps {
  label: string;
  placeholder: string;
  markerColor: string;
  value: string;
  onSelect: (lat: number, lon: number, displayName: string) => void;
}

function shorten(name: string): string {
  // Take first two comma-separated parts, e.g. "Hollywood Blvd, Los Angeles"
  const parts = name.split(",").map((s) => s.trim());
  return parts.slice(0, 2).join(", ");
}

export default function AddressInput({
  label,
  placeholder,
  markerColor,
  value,
  onSelect,
}: AddressInputProps) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { results, loading, search, clear } = useNominatim();

  // Sync external value changes (e.g. swap)
  useEffect(() => {
    setText(value);
  }, [value]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setText(val);
    search(val);
    setOpen(true);
  };

  const handleSelect = (result: NominatimResult) => {
    const short = shorten(result.display_name);
    setText(short);
    setOpen(false);
    clear();
    onSelect(parseFloat(result.lat), parseFloat(result.lon), short);
  };

  return (
    <div ref={wrapperRef} className="relative">
      <label className="flex items-center gap-1.5 text-sm font-medium mb-1">
        <span
          className="inline-block w-3 h-3 rounded-full"
          style={{ backgroundColor: markerColor }}
        />
        {label}
      </label>
      <input
        type="text"
        value={text}
        onChange={handleChange}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder}
        className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
      {loading && (
        <span className="absolute right-2 top-8 text-xs text-gray-400">...</span>
      )}
      {open && results.length > 0 && (
        <ul className="absolute z-50 w-full bg-white border rounded shadow-lg mt-0.5 max-h-48 overflow-y-auto">
          {results.map((r) => (
            <li
              key={r.place_id}
              onClick={() => handleSelect(r)}
              className="px-2 py-1.5 text-sm cursor-pointer hover:bg-blue-50 border-b last:border-b-0"
            >
              {shorten(r.display_name)}
              <span className="block text-xs text-gray-400 truncate">
                {r.display_name}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
