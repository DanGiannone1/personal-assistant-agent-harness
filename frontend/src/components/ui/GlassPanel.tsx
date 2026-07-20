"use client";

import { motion, HTMLMotionProps } from "framer-motion";
import { ReactNode } from "react";

interface GlassPanelProps extends HTMLMotionProps<"div"> {
  children: ReactNode;
  variant?: "heavy" | "light" | "inset";
  hoverEffect?: boolean;
}

/**
 * The foundational structural atom of the CSA Workbench design system.
 * Handles surface backgrounds, backdrop blurs, and subtle borders.
 */
export default function GlassPanel({
  children,
  variant = "light",
  hoverEffect = false,
  className = "",
  ...props
}: GlassPanelProps) {
  const variants = {
    heavy: "bg-surface-1/70 backdrop-blur-2xl border-border-subtle",
    light: "bg-surface-1/50 backdrop-blur-[40px] border-brand-primary/10",
    inset: "bg-app/40 backdrop-blur-md border-border-subtle shadow-inner",
  };

  const hoverClass = hoverEffect 
    ? "hover:border-brand-primary/40 hover:bg-surface-2/60 transition-all duration-500" 
    : "";

  return (
    <motion.div
      className={`rounded-[2rem] border shadow-2xl overflow-hidden ${variants[variant]} ${hoverClass} ${className}`}
      {...props}
    >
      {children}
    </motion.div>
  );
}
