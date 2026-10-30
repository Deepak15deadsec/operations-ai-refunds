import type { SVGProps } from "react";

/** Small inline icon set (24px grid, stroke-based) so the UI has no icon-font dependency. */
const paths = {
  home: "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z",
  ticket: "M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a2 2 0 0 0 0-4zM13 5v14",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  runs: "M4 6h16M4 12h10M4 18h6M17 14l3 3-3 3",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5",
  ledger: "M5 3h11l3 3v15H5zM9 8h6M9 12h6M9 16h4",
  audit: "M12 8v4l3 2M21 12a9 9 0 1 1-3-6.7M21 4v4h-4",
  wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  alert: "M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  mail: "M3 6h18v12H3zM3 7l9 6 9-6",
  money: "M3 7h18v10H3zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 10v.01M18 14v.01",
  arrow: "M5 12h14M13 6l6 6-6 6",
  play: "M7 5v14l11-7z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  truck: "M3 6h11v10H3zM14 9h4l3 3v4h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  chevron: "M9 6l6 6-6 6",
  layers: "M12 3 3 8l9 5 9-5zM3 13l9 5 9-5",
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 16, ...props }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name]} />
    </svg>
  );
}
