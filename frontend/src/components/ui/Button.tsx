import React from "react";
import clsx from "clsx";

const sizeStyles: Record<string, string> = {
  sm: "h-8 rounded-md px-2 text-xs",
  md: "h-10 rounded-md px-3 text-sm",
  lg: "h-12 rounded-lg px-4 text-base",
};

const variantStyles: Record<string, string> = {
  solid: "bg-brand-600 text-white hover:bg-brand-700 focus:ring-brand-500",
  outline: "border border-brand-500 text-brand-600 hover:bg-brand-500/10",
  ghost: "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: "sm" | "md" | "lg";
  variant?: "solid" | "outline" | "ghost";
  className?: string;
  type?: "button" | "submit" | "reset";
}

export const Button: React.FC<ButtonProps> = (props: ButtonProps) => {
  const { size = "md", variant = "solid", className, type = "button", ...rest } = props;

  return (
    <button
      type={type}
      className={clsx(
        "inline-flex items-center justify-center font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60",
        sizeStyles[size],
        variantStyles[variant],
        className
      )}
      {...rest}
    />
  );
};
