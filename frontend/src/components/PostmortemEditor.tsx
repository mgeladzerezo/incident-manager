import { type Editor, EditorContent, type JSONContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";

import { useMe, usePostmortem, useSavePostmortem } from "../api/hooks";
import type { Postmortem } from "../api/types";
import { formatDateTime } from "../lib/format";
import { hasRole } from "../lib/incidents";

const TEMPLATE: JSONContent = {
  type: "doc",
  content: ["Summary", "Impact", "Root cause", "What went well", "Action items"].flatMap(
    (heading) => [
      { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: heading }] },
      { type: "paragraph" },
    ],
  ),
};

export function PostmortemEditor({ incidentId }: { incidentId: number }) {
  const postmortem = usePostmortem(incidentId);
  const me = useMe();

  if (postmortem.isPending || me.isPending) return <p className="text-slate-500">Loading…</p>;
  if (postmortem.isError) return <p className="text-red-700">{postmortem.error.message}</p>;

  const isManager = hasRole(me.data?.roles ?? [], "manager");
  // The editor reads its content once on mount, so it is only mounted after the load.
  return <LoadedEditor incidentId={incidentId} saved={postmortem.data} isManager={isManager} />;
}

interface LoadedEditorProps {
  incidentId: number;
  saved: Postmortem | null;
  isManager: boolean;
}

function LoadedEditor({ incidentId, saved, isManager }: LoadedEditorProps) {
  const save = useSavePostmortem(incidentId);
  const published = saved?.status === "published";
  const editable = !published || isManager;
  const editor = useEditor({
    extensions: [StarterKit],
    content: (saved?.content as JSONContent | undefined) ?? TEMPLATE,
    editable,
  });

  if (editor === null) return null;

  const store = (status: "draft" | "published") =>
    save.mutate({ content: editor.getJSON(), status });

  return (
    <div>
      <div className="postmortem-editor rounded-lg border border-slate-200 bg-white">
        {editable && <Toolbar editor={editor} />}
        <EditorContent editor={editor} />
      </div>
      <div className="mt-3 flex items-center gap-3 text-sm">
        {editable && (
          <button
            className="rounded bg-slate-900 px-3 py-1.5 font-medium text-white disabled:opacity-50"
            disabled={save.isPending}
            onClick={() => store(published ? "published" : "draft")}
          >
            {published ? "Save" : "Save draft"}
          </button>
        )}
        {isManager && !published && (
          <button
            className="rounded border border-slate-300 bg-white px-3 py-1.5 font-medium disabled:opacity-50"
            disabled={save.isPending}
            onClick={() => store("published")}
          >
            Publish
          </button>
        )}
        {saved && (
          <span className="text-slate-500">
            {published ? "Published" : "Draft"}, last saved {formatDateTime(saved.updated_at)}
            {saved.updated_by_name && ` by ${saved.updated_by_name}`}
          </span>
        )}
        {save.isError && <span className="text-red-700">{save.error.message}</span>}
      </div>
    </div>
  );
}

function Toolbar({ editor }: { editor: Editor }) {
  const items = [
    { label: "Bold", run: () => editor.chain().focus().toggleBold().run() },
    { label: "Italic", run: () => editor.chain().focus().toggleItalic().run() },
    { label: "Heading", run: () => editor.chain().focus().toggleHeading({ level: 2 }).run() },
    { label: "Bullets", run: () => editor.chain().focus().toggleBulletList().run() },
    { label: "Numbered", run: () => editor.chain().focus().toggleOrderedList().run() },
    { label: "Code", run: () => editor.chain().focus().toggleCode().run() },
  ];
  return (
    <div className="flex gap-1 border-b border-slate-200 p-2">
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          className="rounded px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
          onClick={item.run}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
