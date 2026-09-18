import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/** 段落间距压到最小,排版紧凑 */
const components: Components = {
  p: ({ node, ...props }) => <p style={{ margin: "0 0 2px" }} {...props} />,
  ul: ({ node, ...props }) => (
    <ul style={{ margin: "0 0 2px", paddingLeft: 20 }} {...props} />
  ),
  ol: ({ node, ...props }) => (
    <ol style={{ margin: "0 0 2px", paddingLeft: 20 }} {...props} />
  ),
  li: ({ node, ...props }) => <li style={{ marginBottom: 2 }} {...props} />,
  h1: ({ node, ...props }) => (
    <h1 style={{ fontSize: 20, margin: "6px 0 2px" }} {...props} />
  ),
  h2: ({ node, ...props }) => (
    <h2 style={{ fontSize: 18, margin: "6px 0 2px" }} {...props} />
  ),
  h3: ({ node, ...props }) => (
    <h3 style={{ fontSize: 16, margin: "6px 0 2px" }} {...props} />
  ),
  hr: ({ node, ...props }) => (
    <hr
      style={{ margin: "6px 0", border: "none", borderTop: "1px solid #eee" }}
      {...props}
    />
  ),
  blockquote: ({ node, ...props }) => (
    <blockquote
      style={{
        margin: "0 0 2px",
        padding: "2px 12px",
        borderLeft: "3px solid #e0e0e0",
        color: "#666",
      }}
      {...props}
    />
  ),
  a: ({ node, ...props }) => (
    <a {...props} target="_blank" rel="noreferrer" style={{ color: "#7C5CFC" }} />
  ),
  code: ({ node, ...props }) => (
    <code
      {...props}
      style={{
        background: "#f0f0f0",
        padding: "2px 5px",
        borderRadius: 4,
        fontSize: 13,
        fontFamily: "monospace",
      }}
    />
  ),
  pre: ({ node, ...props }) => (
    <pre
      {...props}
      style={{
        background: "#f6f8fa",
        padding: 12,
        borderRadius: 8,
        overflowX: "auto",
        fontSize: 13,
      }}
    />
  ),
  table: ({ node, ...props }) => (
    <div style={{ overflowX: "auto", margin: "4px 0" }}>
      <table
        {...props}
        style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: 14,
        }}
      />
    </div>
  ),
  th: ({ node, ...props }) => (
    <th
      {...props}
      style={{
        border: "1px solid #e0e0e0",
        padding: "6px 10px",
        background: "#fafafa",
        textAlign: "left",
        whiteSpace: "nowrap",
      }}
    />
  ),
  td: ({ node, ...props }) => (
    <td
      {...props}
      style={{
        border: "1px solid #e0e0e0",
        padding: "6px 10px",
        whiteSpace: "nowrap",
      }}
    />
  ),
};

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div style={{ fontSize: 15, lineHeight: 1.7, whiteSpace: "normal" }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownMessage;
