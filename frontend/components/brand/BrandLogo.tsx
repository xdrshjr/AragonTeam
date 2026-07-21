import Image from "next/image";

interface BrandLockupProps {
  className?: string;
  priority?: boolean;
}

/**
 * Displays the selected lockup without rewriting the source artwork.
 * The generated canvas contains generous presentation whitespace, so the
 * image is positioned through a fixed viewport around the original mark.
 */
export function BrandLockup({
  className = "h-8 w-[190px]",
  priority = false,
}: BrandLockupProps) {
  return (
    <span
      aria-label="AragonTeam"
      className={`relative inline-block shrink-0 overflow-hidden ${className}`}
      role="img"
    >
      <Image
        alt=""
        aria-hidden="true"
        className="absolute left-0 top-0 h-auto max-w-none"
        height={809}
        priority={priority}
        sizes="320px"
        src="/brand/aragonteam-lockup.png"
        style={{
          transform: "translate(-11.48%, -33.37%)",
          width: "128.35%",
        }}
        width={1942}
      />
    </span>
  );
}
