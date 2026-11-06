type JsonEditorProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
};

export default function JsonEditor(props: JsonEditorProps) {
  return (
    <label className="field-block">
      <span>{props.label}</span>
      <textarea
        rows={props.rows ?? 10}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        placeholder={props.placeholder}
      />
    </label>
  );
}
