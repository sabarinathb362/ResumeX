/**
 * ResumeTextCanvas — the "Text" view as a real editor (Tiptap 3 / ProseMirror).
 *
 *  - Only bullet text is editable. Name, headings and entry lines are atom nodes.
 *  - A filter plugin rejects any transaction that adds, removes or reorders blocks,
 *    so typing can never break the statement -> resume_data mapping used by export.
 *  - Typing is debounced into onEditText(sid, text); accepted suggestions arrive via
 *    the `edits` prop and are patched into the one paragraph they change (undoable,
 *    with a short highlight), so the cursor and history survive.
 */
import { useEffect, useMemo, useRef } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import { Node, Extension, mergeAttributes } from '@tiptap/core';
import Document from '@tiptap/extension-document';
import Text from '@tiptap/extension-text';
import { UndoRedo } from '@tiptap/extensions';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';

const LABEL_CLASS = { name: 'ed-paper-name', contact: 'ed-paper-contact', heading: 'ed-paper-h', title: 'ed-paper-title', sub: 'ed-paper-sub' };

const Label = Node.create({
  name: 'rxLabel',
  group: 'block',
  atom: true,
  selectable: false,
  draggable: false,
  addAttributes() {
    return { text: { default: '' }, kind: { default: 'title' } };
  },
  parseHTML() {
    return [{ tag: 'div[data-rx-label]' }];
  },
  renderHTML({ node }) {
    return ['div', { 'data-rx-label': node.attrs.kind, class: LABEL_CLASS[node.attrs.kind] || '', contenteditable: 'false' }, node.attrs.text];
  },
});

const StatementNode = Node.create({
  name: 'statement',
  group: 'block',
  content: 'text*',
  marks: '',
  addAttributes() {
    return {
      sid: { default: null, parseHTML: el => el.getAttribute('data-sid'), renderHTML: a => ({ 'data-sid': a.sid }) },
      grade: { default: null, renderHTML: a => (a.grade ? { 'data-grade': a.grade } : {}) },
    };
  },
  parseHTML() {
    return [{ tag: 'p[data-sid]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ['p', mergeAttributes(HTMLAttributes, { class: 'ed-paper-st' }), 0];
  },
});

const lockKey = new PluginKey('rx-structure-lock');
const decoKey = new PluginKey('rx-decor');

function signature(doc) {
  const ids = [];
  doc.forEach(n => ids.push(n.type.name === 'statement' ? n.attrs.sid : `#${n.attrs.kind}:${n.attrs.text}`));
  return ids.join('|');
}

const StructureLock = Extension.create({
  name: 'rxStructureLock',
  addKeyboardShortcuts() {
    // A bullet is one paragraph: Enter would create a statement with no resume_data path.
    return { Enter: () => true, 'Shift-Enter': () => true, 'Mod-Enter': () => true };
  },
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: lockKey,
        filterTransaction: (tr, state) => !tr.docChanged || !!tr.getMeta('rx-load') || signature(tr.doc) === signature(state.doc),
      }),
      new Plugin({
        key: decoKey,
        state: {
          init: () => ({ selected: null, edited: {}, severity: {}, flash: null, grades: true }),
          apply: (tr, value) => (tr.getMeta(decoKey) ? { ...value, ...tr.getMeta(decoKey) } : value),
        },
        props: {
          decorations(state) {
            const v = decoKey.getState(state);
            const decos = [];
            state.doc.forEach((node, pos) => {
              if (node.type.name !== 'statement') return;
              const sid = node.attrs.sid;
              const cls = [];
              if (sid === v.selected) cls.push('is-sel');
              if (v.edited[sid]) cls.push('is-edited');
              if (v.severity[sid]) cls.push(`sev-${v.severity[sid]}`);
              if (v.flash === sid) cls.push('rx-morph');
              if (!v.grades) cls.push('no-grade');
              if (cls.length) decos.push(Decoration.node(pos, pos + node.nodeSize, { class: cls.join(' ') }));
            });
            return DecorationSet.create(state.doc, decos);
          },
        },
      }),
    ];
  },
});

export function buildDoc(resumeData, sections, textOf, grades, additions) {
  const content = [];
  const label = (kind, text) => { if (text) content.push({ type: 'rxLabel', attrs: { kind, text } }); };
  const stmt = (sid, text, grade) => content.push({
    type: 'statement', attrs: { sid, grade: grade || null }, content: text ? [{ type: 'text', text }] : [],
  });
  const c = resumeData?.contact || {};
  label('name', c.name || '');
  label('contact', [c.email, c.phone, c.linkedin, c.github].filter(Boolean).join(' · '));
  for (const sec of sections) {
    label('heading', sec.heading);
    for (const e of sec.entries || []) {
      const head = `${e.title || ''}${e.tags?.length ? ` — ${e.tags.join(', ')}` : ''}`;
      label('title', [head, e.dates].filter(Boolean).join('    '));
      label('sub', e.subtitle);
      for (const st of e.statements || []) stmt(st.id, textOf(st.id), grades[st.id]?.grade);
      for (const [sid] of additions.filter(([, a]) => a.entryId === e.id)) stmt(sid, textOf(sid), null);
    }
  }
  return { type: 'doc', content };
}

function sidAt(state) {
  const { $from } = state.selection;
  for (let d = $from.depth; d >= 0; d--) {
    const n = $from.node(d);
    if (n.type.name === 'statement') return n.attrs.sid;
  }
  return null;
}

export const RX_EXTENSIONS = [Document, Text, Label, StatementNode, UndoRedo, StructureLock];

export default function ResumeTextCanvas({
  resumeData, sections, edits, grades, severityBySid = {}, selectedSid, showGrades = true,
  onSelect, onEditText,
}) {
  const originals = useMemo(() => {
    const m = {};
    for (const s of sections) for (const e of s.entries || []) for (const st of e.statements || []) m[st.id] = st.text;
    return m;
  }, [sections]);
  const additions = useMemo(() => Object.entries(edits).filter(([k]) => k.startsWith('add:')), [edits]);
  const textOf = (sid) => edits[sid]?.text ?? originals[sid] ?? '';
  const structure = useMemo(() => JSON.stringify([sections.map(s => s.id), additions.map(([k]) => k)]), [sections, additions]);

  const latest = useRef({});
  latest.current = { onSelect, onEditText, edits, originals };
  const debounce = useRef(null);
  const lastSid = useRef(null);
  const fromEditor = useRef({}); // sid -> last text this editor reported (so we never overwrite live typing)

  const editor = useEditor({
    extensions: RX_EXTENSIONS,
    content: buildDoc(resumeData, sections, textOf, grades, additions),
    shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: { class: 'ed-paper rx-canvas', spellcheck: 'true', 'aria-label': 'Resume text editor' },
      handlePaste(view, event) {
        const text = event.clipboardData?.getData('text/plain');
        if (text == null) return false;
        view.dispatch(view.state.tr.insertText(text.replace(/\s*\n+\s*/g, ' ')));
        return true;
      },
    },
    onUpdate({ editor: ed, transaction }) {
      if (transaction.getMeta('rx-external') || transaction.getMeta('rx-load')) return;
      clearTimeout(debounce.current);
      debounce.current = setTimeout(() => {
        const { edits: cur, originals: orig, onEditText: cb } = latest.current;
        ed.state.doc.forEach(node => {
          if (node.type.name !== 'statement') return;
          const sid = node.attrs.sid;
          const text = node.textContent;
          if (text !== (cur[sid]?.text ?? orig[sid] ?? '')) {
            fromEditor.current[sid] = text;
            cb?.(sid, text);
          }
        });
      }, 400);
    },
    onSelectionUpdate({ editor: ed }) {
      const sid = sidAt(ed.state);
      if (sid && sid !== lastSid.current) {
        lastSid.current = sid;
        latest.current.onSelect?.(sid);
      }
    },
  });

  // Rebuild only when the block structure changes (new resume, added bullet).
  useEffect(() => {
    if (!editor) return;
    const json = buildDoc(resumeData, sections, textOf, grades, additions);
    const node = editor.schema.nodeFromJSON(json);
    if (signature(node) === signature(editor.state.doc)) return;
    const tr = editor.state.tr.replaceWith(0, editor.state.doc.content.size, node.content)
      .setMeta('rx-load', true).setMeta('addToHistory', false);
    editor.view.dispatch(tr);
  }, [editor, structure]); // eslint-disable-line react-hooks/exhaustive-deps

  // Patch paragraphs whose text changed outside the editor (accept / undo in the sidebar).
  useEffect(() => {
    if (!editor) return;
    let tr = editor.state.tr;
    let flash = null;
    editor.state.doc.forEach((node, pos) => {
      if (node.type.name !== 'statement') return;
      const sid = node.attrs.sid;
      const want = textOf(sid);
      if (node.textContent === want) return;
      if (edits[sid] && edits[sid].text === fromEditor.current[sid]) return; // came from typing here
      const from = tr.mapping.map(pos + 1);
      const to = tr.mapping.map(pos + node.nodeSize - 1);
      tr = want ? tr.replaceWith(from, to, editor.schema.text(want)) : tr.delete(from, to);
      flash = sid;
    });
    if (tr.docChanged) {
      editor.view.dispatch(tr.setMeta('rx-external', true).setMeta(decoKey, { flash }));
      setTimeout(() => { if (!editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(decoKey, { flash: null })); }, 700);
    }
  }, [editor, edits]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selection, edited markers, severity tints, grade chips.
  useEffect(() => {
    if (!editor) return;
    const edited = Object.fromEntries(Object.keys(edits).map(k => [k, true]));
    editor.view.dispatch(editor.state.tr.setMeta(decoKey, { selected: selectedSid, edited, severity: severityBySid, grades: showGrades }));
  }, [editor, selectedSid, edits, severityBySid, showGrades]);

  useEffect(() => { lastSid.current = selectedSid; }, [selectedSid]);
  useEffect(() => () => clearTimeout(debounce.current), []);

  return <EditorContent editor={editor} />;
}
