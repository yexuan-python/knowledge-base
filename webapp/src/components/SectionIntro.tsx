type SectionIntroProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export default function SectionIntro(props: SectionIntroProps) {
  return (
    <div className="panel-header">
      <div>
        <div className="eyebrow">{props.eyebrow}</div>
        <h2>{props.title}</h2>
        <p>{props.description}</p>
      </div>
    </div>
  );
}
