// The app frame every admin shares: collapsible sidebar, sticky header with a
// breadcrumb title and the signed-in actor, and the live-refresh note. An app
// supplies its nav and screens; each option below exists because an admin
// that adopted the frame needed it.
//
// - Nav groups: give items a `group` and they are listed under that label.
// - A scoped nav: an item's `scope(route)` may replace the sidebar with the
//   sections of one record (a run, a notebook), with a link back out.
// - An `aside`: a region on the right that stays put across screens and can
//   be hidden; under the mobile breakpoint it is a bar along the bottom that
//   opens a sheet.
// - `liveNote` is the status line above each screen; omitted, it says how
//   often the screen checks for updates.
import React, { useEffect, useState } from "react";
import { ChevronLeft, ChevronUp, PanelRight, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { APP } from "@/app.config";
import { cn } from "@/lib/utils";
import { href, useRoute, type Route } from "@/lib/route";
import { POLL_MS, useSession } from "@/lib/transport";

export type NavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
  render: (route: Route) => React.ReactNode;
  /** Reachable by link but not listed in the sidebar. */
  hidden?: boolean;
  /** For a hidden item: the nav id to highlight and to offer as the crumb. */
  parent?: string;
  /** Section label. Items sharing one are listed together, in order of first use. */
  group?: string;
  /** Inside one record, the sections to show in place of the app's nav; `null` for the usual nav. */
  scope?: (route: Route) => NavScope | null;
};

/** One link in a scoped nav. Give each an icon: it is all that shows when the sidebar is collapsed. */
export type ScopeLink = { id: string; label: string; href: string; icon?: LucideIcon; group?: string };

export type NavScope = {
  /** What the scope is: a record's id or name. */
  title: string;
  /** What kind of thing it is, shown under the title. */
  kind?: string;
  /** The way back out, e.g. `{ label: "All runs", href: href("runs") }`. */
  back: { label: string; href: string };
  items: ScopeLink[];
  /** The id of the current section. Default: the first. */
  active?: string;
};

export type AsideSlot = {
  /** Names the region: the toggle, the mobile bar and the sheet title. */
  label: string;
  icon?: LucideIcon;
  render: (route: Route) => React.ReactNode;
  /** One short line for the mobile bar, e.g. the latest entry. */
  summary?: React.ReactNode;
};

export type FrameOptions = {
  /** The status line above each screen. `false` removes it; a node replaces it. Default: the polling note. */
  liveNote?: React.ReactNode | false;
  /** What shows at the right of the header. `false` shows nothing and makes no session call. Default: the signed-in person. */
  actor?: React.ReactNode | false;
  /** Extra header content before the actor: a global search, a data stamp. */
  headerEnd?: React.ReactNode;
  /** Classes for the content column, for example "mx-auto max-w-6xl". */
  contentClassName?: string;
  sidebarWidth?: string;
  /** A region on the right that persists across screens; a bottom bar and sheet on phones. */
  aside?: AsideSlot;
};

/** Dark mode follows the OS preference through the theme's `.dark` class. */
function useSystemTheme() {
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => document.documentElement.classList.toggle("dark", query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);
}

/** Items grouped by label, in order of first appearance; unlabelled items first. */
function grouped<T extends { group?: string }>(items: T[]): [string, T[]][] {
  const out = new Map<string, T[]>();
  for (const item of items) {
    const key = item.group ?? "";
    if (!out.has(key)) out.set(key, []);
    out.get(key)!.push(item);
  }
  return [...out.entries()].sort(([a], [b]) => (a === "" ? -1 : b === "" ? 1 : 0));
}

type Link = { id: string; label: string; href: string; icon?: LucideIcon; group?: string };

function NavLinks({ links, active, label }: { links: Link[]; active: string; label: string }) {
  const { setOpenMobile } = useSidebar();
  return (
    <nav aria-label={label}>
      {grouped(links).map(([group, items]) => (
        <SidebarGroup key={group || "_"}>
          {group && <SidebarGroupLabel>{group}</SidebarGroupLabel>}
          <SidebarMenu>
            {items.map((item) => (
              <SidebarMenuItem key={item.id}>
                <SidebarMenuButton asChild isActive={active === item.id} tooltip={item.label}>
                  <a href={item.href} onClick={() => setOpenMobile(false)} aria-current={active === item.id ? "page" : undefined}>
                    {item.icon && <item.icon />}
                    <span>{item.label}</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      ))}
    </nav>
  );
}

function AppSidebar({ nav, view, scope, icon: Icon }: { nav: NavItem[]; view: string; scope: NavScope | null; icon: LucideIcon }) {
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton className="h-auto py-1.5 font-semibold" asChild>
              <a href={href(nav[0].id)} onClick={() => setOpenMobile(false)}>
                <Icon />
                <span className="flex min-w-0 flex-col">
                  <span>{APP.name}</span>
                  <span className="text-xs leading-tight font-normal text-muted-foreground">{APP.tagline}</span>
                </span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent className="gap-0">
        {scope ? (
          <>
            <SidebarGroup className="pb-0">
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild tooltip={scope.back.label} className="text-muted-foreground">
                    <a href={scope.back.href} onClick={() => setOpenMobile(false)}>
                      <ChevronLeft />
                      <span>{scope.back.label}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
              <div className="px-2 pt-2 group-data-[collapsible=icon]:hidden">
                <p className="truncate text-sm font-medium">{scope.title}</p>
                {scope.kind && <p className="text-xs text-muted-foreground">{scope.kind}</p>}
              </div>
            </SidebarGroup>
            <NavLinks links={scope.items} active={scope.active ?? scope.items[0]?.id ?? ""} label={`${scope.title} sections`} />
          </>
        ) : (
          <NavLinks
            links={nav.filter((item) => !item.hidden).map((item) => ({ ...item, href: href(item.id) }))}
            active={view}
            label={`${APP.name} views`}
          />
        )}
      </SidebarContent>
      {APP.promise && (
        <SidebarFooter>
          <div className="px-2 py-1 text-xs leading-relaxed text-muted-foreground group-data-[collapsible=icon]:hidden">{APP.promise}</div>
        </SidebarFooter>
      )}
    </Sidebar>
  );
}

type Crumb = { label: string; href: string };
type TitleState = { title: string; parent?: Crumb };
const TitleContext = React.createContext<(state: TitleState) => void>(() => {});

/**
 * Lets a detail screen put a readable name in the header in place of a raw id,
 * and optionally say where its crumb leads (a review belongs to its deliverable).
 */
export function useTitle(title: string | undefined, parent?: Crumb) {
  const set = React.useContext(TitleContext);
  const parentLabel = parent?.label;
  const parentHref = parent?.href;
  useEffect(() => {
    set({ title: title || "", parent: parentLabel && parentHref ? { label: parentLabel, href: parentHref } : undefined });
    return () => set({ title: "" });
  }, [set, title, parentLabel, parentHref]);
}

/** The signed-in person: a display name when the identity provider gives one, else the actor id. */
function SessionActor() {
  const { session, error } = useSession();
  if (error) return <>{error}</>;
  const name = session?.display_name ? String(session.display_name) : session?.actor ? String(session.actor) : "";
  return (
    <span className="inline-block max-w-40 truncate align-bottom" title={session?.actor ? String(session.actor) : undefined}>
      {name || "signing in…"}
    </span>
  );
}

/** One screen failing must not take the frame down with it. */
class ScreenBoundary extends React.Component<{ children: React.ReactNode; resetKey: string }, { failed: string }> {
  state = { failed: "" };
  static getDerivedStateFromError(error: unknown) {
    return { failed: error instanceof Error ? error.message : "Unknown error" };
  }
  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: "" });
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm">
        <p className="font-medium">This screen could not be shown.</p>
        <p className="mt-1 text-xs text-muted-foreground">{this.state.failed}</p>
        <button type="button" className="mt-2 text-xs underline underline-offset-2" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

const asideKey = `${APP.id}.aside`;

function readAsideOpen(): boolean {
  try {
    return localStorage.getItem(asideKey) !== "closed";
  } catch {
    return true;
  }
}

/** The aside on a wide screen: a column on the right, as tall as the window. */
function AsideColumn({ aside, route }: { aside: AsideSlot; route: Route }) {
  return (
    <aside aria-label={aside.label} className="sticky top-0 hidden h-svh w-72 shrink-0 overflow-y-auto border-l bg-background md:block lg:w-80">
      <div className="flex min-h-12 items-center border-b px-4">
        <h2 className="text-sm font-medium">{aside.label}</h2>
      </div>
      <div className="p-4">{aside.render(route)}</div>
    </aside>
  );
}

/** The aside on a phone: a bar along the bottom that opens a sheet. */
function AsideBar({ aside, route }: { aside: AsideSlot; route: Route }) {
  const [open, setOpen] = useState(false);
  const Icon = aside.icon ?? PanelRight;
  // A link inside the sheet moves to another screen: get out of its way.
  const at = `${route.view}/${route.parts.join("/")}?${route.params.toString()}`;
  useEffect(() => setOpen(false), [at]);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed inset-x-0 bottom-0 z-20 flex h-12 items-center gap-2 border-t bg-background px-3 text-left text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none md:hidden"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="shrink-0 font-medium">{aside.label}</span>
        {aside.summary && <span className="min-w-0 flex-1 truncate text-muted-foreground">{aside.summary}</span>}
        <ChevronUp className="ml-auto size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="bottom" className="max-h-[80svh] gap-0 md:hidden">
          <SheetHeader className="border-b">
            <SheetTitle>{aside.label}</SheetTitle>
            <SheetDescription className="sr-only">{aside.label}, shown on every screen</SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto p-4">{aside.render(route)}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}

export function AppFrame({
  nav,
  icon,
  liveNote,
  actor,
  headerEnd,
  contentClassName,
  sidebarWidth = "13rem",
  aside,
}: { nav: NavItem[]; icon: LucideIcon } & FrameOptions) {
  const route = useRoute();
  const [titled, setTitled] = React.useState<TitleState>({ title: "" });
  const [asideOpen, setAsideOpen] = useState(readAsideOpen);
  useSystemTheme();
  const current = nav.find((item) => item.id === route.view) ?? nav[0];
  const owner = (current.parent && nav.find((item) => item.id === current.parent)) || current;
  const scope = current.scope?.(route) ?? null;
  const detail = titled.title || route.parts.join(" / ");
  const crumb: Crumb | null = titled.parent ?? (detail || owner !== current ? { label: owner.label, href: href(owner.id) } : null);
  const heading = detail || current.label;

  useEffect(() => {
    document.title = detail ? `${APP.name} · ${current.label} · ${detail}` : `${APP.name} · ${current.label}`;
  }, [current.label, detail]);

  const toggleAside = () => {
    setAsideOpen((open) => {
      try {
        localStorage.setItem(asideKey, open ? "closed" : "open");
      } catch {
        // Private mode: the choice lasts for this page only.
      }
      return !open;
    });
  };
  const asideVerb = aside ? `${asideOpen ? "Hide" : "Show"} ${aside.label.toLowerCase()}` : "";

  return (
    <TooltipProvider>
      <SidebarProvider style={{ "--sidebar-width": sidebarWidth } as React.CSSProperties}>
        <AppSidebar nav={nav} view={owner.id} scope={scope} icon={icon} />
        <SidebarInset className="min-w-0 flex-row">
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-10 flex min-h-12 shrink-0 items-center justify-between gap-2 border-b bg-background px-3 sm:px-5">
              <div className="flex min-w-0 items-center gap-2">
                <SidebarTrigger />
                <Separator orientation="vertical" className="h-4!" />
                {crumb && (
                  <a href={crumb.href} className="shrink-0 text-xs text-muted-foreground">
                    {crumb.label} /
                  </a>
                )}
                <h1 className="truncate text-sm font-medium">{heading}</h1>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {headerEnd}
                {actor !== false && <span className="text-xs text-muted-foreground">{actor ?? <SessionActor />}</span>}
                {aside && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="hidden size-7 md:inline-flex"
                    onClick={toggleAside}
                    aria-pressed={asideOpen}
                    aria-label={asideVerb}
                    title={asideVerb}
                  >
                    <PanelRight aria-hidden="true" />
                  </Button>
                )}
              </div>
            </header>
            <div className={cn("w-full min-w-0 space-y-5 p-3 sm:p-5", aside && "pb-16 md:pb-5", contentClassName)}>
              {liveNote !== false && <div className="text-xs text-muted-foreground">{liveNote ?? `Live · checks for updates every ${POLL_MS / 1000} seconds`}</div>}
              <TitleContext.Provider value={setTitled}>
                <section id={current.id} className="min-w-0 space-y-5">
                  <ScreenBoundary resetKey={`${route.view}/${route.parts.join("/")}`}>{current.render(route)}</ScreenBoundary>
                </section>
              </TitleContext.Provider>
            </div>
          </div>
          {aside && asideOpen && <AsideColumn aside={aside} route={route} />}
          {aside && <AsideBar aside={aside} route={route} />}
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
