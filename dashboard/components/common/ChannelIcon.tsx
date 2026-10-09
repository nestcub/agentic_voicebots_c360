import {
  Briefcase,
  Car,
  Folder,
  Headphones,
  HeartHandshake,
  Megaphone,
  Phone,
  ShoppingCart,
  Sparkles,
  Store,
  Truck,
  Wrench,
  type LucideIcon,
} from "lucide-react";

// Channel.icon is a free-text field. New channels store one of these keys;
// anything else (including emoji saved before the revamp) falls back to Folder.
export const CHANNEL_ICONS: Record<string, LucideIcon> = {
  folder: Folder,
  car: Car,
  wrench: Wrench,
  phone: Phone,
  headphones: Headphones,
  megaphone: Megaphone,
  "shopping-cart": ShoppingCart,
  store: Store,
  briefcase: Briefcase,
  truck: Truck,
  "heart-handshake": HeartHandshake,
  sparkles: Sparkles,
};

export const DEFAULT_CHANNEL_COLOR = "#2563eb";

export function channelIcon(icon: string | null | undefined): LucideIcon {
  return (icon && CHANNEL_ICONS[icon]) || Folder;
}

export function ChannelIconTile({
  icon,
  color,
  size = "md",
}: {
  icon: string | null | undefined;
  color: string | null | undefined;
  size?: "sm" | "md";
}) {
  const Icon = channelIcon(icon);
  const c = color || DEFAULT_CHANNEL_COLOR;
  const box = size === "sm" ? "w-8 h-8 rounded-lg" : "w-10 h-10 rounded-xl";
  return (
    <span className={`${box} shrink-0 flex items-center justify-center`} style={{ backgroundColor: `${c}1f`, color: c }}>
      <Icon className={size === "sm" ? "w-4 h-4" : "w-5 h-5"} />
    </span>
  );
}
