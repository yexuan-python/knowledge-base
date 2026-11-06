import type { ReactNode } from "react";

type ModalProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
};

export default function Modal(props: ModalProps) {
  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div
        className="modal-card"
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <div className="modal-header">
          <h3>{props.title}</h3>
          <button type="button" className="secondary-button modal-close" onClick={props.onClose}>
            关闭
          </button>
        </div>
        <div className="modal-body">{props.children}</div>
      </div>
    </div>
  );
}
