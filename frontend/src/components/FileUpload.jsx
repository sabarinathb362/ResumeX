import { useState, useRef, useCallback } from 'react';

export default function FileUpload({ onFileSelect, accept, label, subtitle, disabled }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const inputRef = useRef(null);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setSelectedFile(file);
      onFileSelect?.(file);
    }
  }, [onFileSelect]);

  const handleClick = () => {
    if (!disabled) inputRef.current?.click();
  };

  const handleChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setSelectedFile(file);
      onFileSelect?.(file);
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  return (
    <div
      className={`upload-zone ${isDragOver ? 'drag-over' : ''} ${disabled ? 'disabled' : ''}`}
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : {}}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept || '.pdf,.docx,.doc'}
        onChange={handleChange}
        style={{ display: 'none' }}
        disabled={disabled}
      />

      {selectedFile ? (
        <div style={{ position: 'relative', zIndex: 1 }}>
          <span className="icon"></span>
          <div className="title">{selectedFile.name}</div>
          <div className="subtitle">{formatSize(selectedFile.size)}</div>
          <div style={{ marginTop: '0.75rem', fontSize: '0.8125rem', color: 'var(--accent-success)' }}>
            Ready to upload
          </div>
        </div>
      ) : (
        <div style={{ position: 'relative', zIndex: 1 }}>
          <span className="icon"></span>
          <div className="title">{label || 'Drop your resume here'}</div>
          <div className="subtitle">{subtitle || 'PDF or DOCX • Max 10 MB'}</div>
        </div>
      )}
    </div>
  );
}
